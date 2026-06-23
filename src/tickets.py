"""竞彩胜平负（HAD）票单合法性校验规则。

本模块不负责下注，仅校验手动构建的票单是否符合项目竞彩规则。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from itertools import product
from operator import mul
import re

from src.sp_movement import latest_records


HAD_PLAY_TYPE = "had"
HAD_OPTIONS = frozenset({"H", "D", "A"})
SINGLE_PASS_TYPE = "single"
PASS_TYPE_RE = re.compile(r"^(\d+)x1$")


class TicketValidationError(ValueError):
    """票单违反竞彩票单构建规则时抛出。"""


@dataclass(frozen=True)
class HadSelection:
    """单场比赛的胜平负选项。

    option_codes 可包含一个或多个 H/D/A，用于多选比赛。
    is_single 来源于竞彩固定奖金 API 的 singleList 标志。
    """

    match_id: str
    option_codes: tuple[str, ...]
    is_single: bool = False
    match_status: str = "1"
    play_type: str = HAD_PLAY_TYPE


@dataclass(frozen=True)
class Ticket:
    """手动构建的胜平负票单。"""

    selections: tuple[HadSelection, ...]
    pass_type: str
    stake_per_unit: int = 2
    multiplier: int = 1

    @property
    def unit_count(self) -> int:
        """乘以倍数前的基本投注单位数。"""
        return reduce(mul, (len(s.option_codes) for s in self.selections), 1)

    @property
    def amount(self) -> int:
        """票单金额（人民币）。"""
        return self.unit_count * self.stake_per_unit * self.multiplier


@dataclass(frozen=True)
class TicketCombinationQuote:
    """基于当前 SP 定价的一个可能中奖组合。"""

    options: tuple[tuple[str, str], ...]
    combined_sp: float
    potential_payout: float


@dataclass(frozen=True)
class TicketQuote:
    """基于最新刷新 SP 的票单价格与潜在赔付。"""

    ticket: Ticket
    snapshot_times: tuple[str, ...]
    option_sp: dict[tuple[str, str], float]
    combinations: tuple[TicketCombinationQuote, ...]
    min_potential_payout: float
    max_potential_payout: float


def validate_ticket(ticket: Ticket) -> Ticket:
    """校验胜平负票单，合法时返回该票单。

    执行规则：
    - 仅允许胜平负（had）玩法。
    - 选项必须为 H/D/A。
    - 同一比赛在票单中只能出现一次。
    - 单关票单必须恰好包含一场比赛，且 is_single 必须为 True。
    - 串关票单必须为 Nx1 格式，至少包含两场比赛，且 N 须与比赛场数一致。
    - 每场选中的比赛必须处于在售状态（match_status == "1"）。
    """
    if ticket.stake_per_unit <= 0:
        raise TicketValidationError("stake_per_unit must be positive")
    if ticket.multiplier <= 0:
        raise TicketValidationError("multiplier must be positive")
    if not ticket.selections:
        raise TicketValidationError("ticket must contain at least one selection")

    _validate_selections(ticket.selections)

    if ticket.pass_type == SINGLE_PASS_TYPE:
        _validate_single(ticket.selections)
        return ticket

    _validate_parlay(ticket.selections, ticket.pass_type)
    return ticket


def make_had_selection(
    match_id: str,
    option_codes: list[str] | tuple[str, ...],
    *,
    is_single: bool = False,
    match_status: str = "1",
) -> HadSelection:
    """根据用户或模型输出构建标准化的胜平负选项。"""
    normalized = tuple(dict.fromkeys(code.upper() for code in option_codes))
    return HadSelection(
        match_id=str(match_id),
        option_codes=normalized,
        is_single=bool(is_single),
        match_status=str(match_status),
    )


def make_had_selection_from_sp_records(
    match_id: str,
    option_codes: list[str] | tuple[str, ...],
    sp_records: list[dict],
    *,
    match_status: str = "1",
) -> HadSelection:
    """使用已获取的 SP 记录构建胜平负选项，并推断单关支持状态。"""
    selection = make_had_selection(
        match_id,
        option_codes,
        is_single=False,
        match_status=match_status,
    )
    selected_options = set(selection.option_codes)
    matching_records = [
        record for record in sp_records
        if str(record.get("match_id")) == selection.match_id
        and record.get("play_type") == HAD_PLAY_TYPE
        and record.get("option_code") in selected_options
    ]
    found_options = {record.get("option_code") for record in matching_records}
    missing_options = selected_options - found_options
    if missing_options:
        raise TicketValidationError(
            f"missing had SP records for options: {', '.join(sorted(missing_options))}"
        )

    is_single = any(_truthy_single_flag(record.get("is_single")) for record in matching_records)
    return HadSelection(
        match_id=selection.match_id,
        option_codes=selection.option_codes,
        is_single=is_single,
        match_status=selection.match_status,
    )


def build_ticket(
    selections: list[HadSelection] | tuple[HadSelection, ...],
    pass_type: str,
    *,
    stake_per_unit: int = 2,
    multiplier: int = 1,
) -> Ticket:
    """创建并校验胜平负票单。"""
    ticket = Ticket(
        selections=tuple(selections),
        pass_type=pass_type,
        stake_per_unit=stake_per_unit,
        multiplier=multiplier,
    )
    return validate_ticket(ticket)


def quote_ticket_with_latest_sp(ticket: Ticket, sp_records: list[dict]) -> TicketQuote:
    """使用最新的胜平负 SP 记录重新计算票单价格和赔付区间。

    请在手动购彩前立即调用。本函数不会冻结或下单票单；
    最终奖金仍以竞彩成功出票时的 SP 为准。
    """
    validate_ticket(ticket)
    current_records = latest_records(sp_records)
    index = {
        (str(record.get("match_id")), str(record.get("option_code"))): record
        for record in current_records
        if record.get("play_type") == HAD_PLAY_TYPE
    }

    option_sp: dict[tuple[str, str], float] = {}
    snapshot_times = set()
    per_match_options = []
    for selection in ticket.selections:
        quoted_options = []
        for option_code in selection.option_codes:
            key = (selection.match_id, option_code)
            record = index.get(key)
            if record is None:
                raise TicketValidationError(
                    f"missing latest HAD SP for match={selection.match_id} option={option_code}"
                )
            sp_value = float(record["sp_value"])
            option_sp[key] = sp_value
            snapshot_times.add(str(record.get("snapshot_time", "")))
            quoted_options.append((key, sp_value))
        per_match_options.append(quoted_options)

    combinations = []
    for combo in product(*per_match_options):
        combined_sp = round(reduce(mul, (sp for _, sp in combo), 1.0), 4)
        potential_payout = round(combined_sp * ticket.stake_per_unit * ticket.multiplier, 2)
        combinations.append(TicketCombinationQuote(
            options=tuple(key for key, _ in combo),
            combined_sp=combined_sp,
            potential_payout=potential_payout,
        ))

    payouts = [combo.potential_payout for combo in combinations]
    return TicketQuote(
        ticket=ticket,
        snapshot_times=tuple(sorted(snapshot_times)),
        option_sp=option_sp,
        combinations=tuple(combinations),
        min_potential_payout=min(payouts),
        max_potential_payout=max(payouts),
    )


def _validate_selections(selections: tuple[HadSelection, ...]) -> None:
    seen_match_ids = set()
    for selection in selections:
        if selection.play_type != HAD_PLAY_TYPE:
            raise TicketValidationError("only had play type is supported")
        if not selection.match_id:
            raise TicketValidationError("match_id is required")
        if selection.match_id in seen_match_ids:
            raise TicketValidationError("same match cannot appear more than once in one ticket")
        seen_match_ids.add(selection.match_id)
        if selection.match_status != "1":
            raise TicketValidationError("selected match is not currently in sale status")
        if not selection.option_codes:
            raise TicketValidationError("selection must contain at least one option")
        invalid = [code for code in selection.option_codes if code not in HAD_OPTIONS]
        if invalid:
            raise TicketValidationError(f"invalid had option codes: {', '.join(invalid)}")


def _validate_single(selections: tuple[HadSelection, ...]) -> None:
    if len(selections) != 1:
        raise TicketValidationError("single ticket must contain exactly one match")
    if not selections[0].is_single:
        raise TicketValidationError("selected match does not support single betting")


def _validate_parlay(selections: tuple[HadSelection, ...], pass_type: str) -> None:
    if len(selections) < 2:
        raise TicketValidationError("parlay ticket must contain at least two matches")

    match = PASS_TYPE_RE.match(pass_type)
    if not match:
        raise TicketValidationError("parlay pass_type must be Nx1, for example 2x1 or 3x1")

    required_count = int(match.group(1))
    if required_count != len(selections):
        raise TicketValidationError("parlay pass_type count must equal selected match count")


def _truthy_single_flag(value) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)
