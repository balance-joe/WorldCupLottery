-- Betting ledger and Sporttery review queries.
-- Replace :bet_group, :date_from, :date_to, or :match_id with concrete values
-- when running in a SQLite client that does not support named parameters.


-- 1) One bet group: tickets, legs, match info, linked SP snapshot, and result.
SELECT
  t.id AS ticket_id,
  t.bet_group,
  t.ticket_label,
  t.pass_type,
  t.stake_amount,
  t.expected_max_payout,
  t.actual_payout,
  t.profit_loss,
  t.ticket_status,
  s.leg_index,
  s.match_num,
  s.match_id,
  m.league_name,
  m.home_team_name,
  m.away_team_name,
  m.match_time,
  m.home_score_90,
  m.away_score_90,
  m.result_90,
  s.play_type,
  s.option_code,
  s.option_name,
  s.goal_line,
  s.selected_sp,
  s.sp_snapshot_id,
  sp.snapshot_time AS linked_sp_time,
  sp.implied_prob_norm AS linked_sp_weight
FROM betting_ticket t
JOIN betting_ticket_selection s ON s.ticket_id = t.id
LEFT JOIN sporttery_match m ON m.match_id = s.match_id
LEFT JOIN sporttery_sp_snapshot sp ON sp.id = s.sp_snapshot_id
WHERE t.bet_group = :bet_group
ORDER BY t.id, s.leg_index;


-- 2) Current bankroll summary by bet group.
SELECT
  bet_group,
  COUNT(*) AS ticket_count,
  SUM(stake_amount) AS total_stake,
  SUM(expected_max_payout) AS expected_max_payout,
  SUM(COALESCE(actual_payout, 0)) AS actual_payout,
  SUM(COALESCE(profit_loss, 0)) AS profit_loss,
  SUM(CASE WHEN ticket_status = 'pending' THEN stake_amount ELSE 0 END) AS pending_stake,
  SUM(CASE WHEN ticket_status = 'won' THEN 1 ELSE 0 END) AS won_tickets,
  SUM(CASE WHEN ticket_status = 'lost' THEN 1 ELSE 0 END) AS lost_tickets
FROM betting_ticket
GROUP BY bet_group
ORDER BY MIN(placed_at) DESC, bet_group;


-- 3) Open tickets whose matches already have 90-minute results.
-- These are ready for manual/automated settlement.
SELECT
  t.id AS ticket_id,
  t.bet_group,
  t.ticket_label,
  t.pass_type,
  t.stake_amount,
  t.expected_max_payout,
  COUNT(*) AS leg_count,
  SUM(CASE WHEN m.result_90 IS NOT NULL THEN 1 ELSE 0 END) AS resulted_legs,
  GROUP_CONCAT(s.match_num || ' ' || s.option_name || ' result=' || COALESCE(m.result_90, 'NULL'), '; ') AS leg_results
FROM betting_ticket t
JOIN betting_ticket_selection s ON s.ticket_id = t.id
LEFT JOIN sporttery_match m ON m.match_id = s.match_id
WHERE t.ticket_status = 'pending'
GROUP BY t.id
HAVING leg_count = resulted_legs
ORDER BY t.placed_at, t.id;


-- 4) Check whether each had/hhad leg matches the 90-minute result.
-- For hhad, this needs handicap settlement logic; this query only flags had exactly.
SELECT
  t.id AS ticket_id,
  t.ticket_label,
  s.leg_index,
  s.match_num,
  s.play_type,
  s.option_code,
  s.option_name,
  m.result_90,
  CASE
    WHEN s.play_type = 'had' AND m.result_90 IS NULL THEN 'pending'
    WHEN s.play_type = 'had' AND s.option_code = m.result_90 THEN 'hit'
    WHEN s.play_type = 'had' THEN 'miss'
    ELSE 'needs_play_type_logic'
  END AS leg_eval
FROM betting_ticket t
JOIN betting_ticket_selection s ON s.ticket_id = t.id
LEFT JOIN sporttery_match m ON m.match_id = s.match_id
WHERE t.bet_group = :bet_group
ORDER BY t.id, s.leg_index;


-- 5) SP movement for matches that were selected in a bet group.
-- Use this to review whether the bought SP was early, late, or stale.
SELECT
  s.ticket_id,
  s.match_num,
  m.home_team_name,
  m.away_team_name,
  s.play_type,
  s.option_code,
  s.option_name,
  s.selected_sp,
  s.sp_snapshot_time AS bought_sp_time,
  sp.snapshot_time,
  sp.sp_value,
  sp.implied_prob_norm,
  ROUND(sp.sp_value - s.selected_sp, 4) AS sp_vs_bought
FROM betting_ticket_selection s
JOIN betting_ticket t ON t.id = s.ticket_id
LEFT JOIN sporttery_match m ON m.match_id = s.match_id
JOIN sporttery_sp_snapshot sp
  ON sp.match_id = s.match_id
 AND sp.play_type = s.play_type
 AND sp.option_code = s.option_code
WHERE t.bet_group = :bet_group
ORDER BY s.ticket_id, s.leg_index, sp.snapshot_time;


-- 6) Latest SP board for a match, all available play types.
SELECT
  m.match_num,
  m.home_team_name,
  m.away_team_name,
  latest.play_type,
  latest.option_code,
  latest.option_name,
  latest.goal_line,
  latest.sp_value,
  latest.implied_prob_norm,
  latest.snapshot_time
FROM sporttery_match m
JOIN (
  SELECT *
  FROM (
    SELECT
      sp.*,
      ROW_NUMBER() OVER (
        PARTITION BY sp.match_id, sp.play_type, sp.option_code
        ORDER BY sp.snapshot_time DESC, sp.id DESC
      ) AS rn
    FROM sporttery_sp_snapshot sp
    WHERE sp.match_id = :match_id
  )
  WHERE rn = 1
) latest ON latest.match_id = m.match_id
ORDER BY latest.play_type, latest.option_code;


-- 7) Daily exposure: how much stake is tied to each match day.
SELECT
  DATE(m.match_time) AS match_date,
  COUNT(DISTINCT t.id) AS ticket_count,
  COUNT(*) AS leg_count,
  SUM(t.stake_amount) AS duplicated_ticket_stake,
  GROUP_CONCAT(DISTINCT t.bet_group) AS bet_groups
FROM betting_ticket t
JOIN betting_ticket_selection s ON s.ticket_id = t.id
LEFT JOIN sporttery_match m ON m.match_id = s.match_id
GROUP BY DATE(m.match_time)
ORDER BY match_date;


-- 8) Strategy review: performance by play type and option after settlement.
SELECT
  s.play_type,
  s.option_code,
  s.option_name,
  COUNT(*) AS leg_count,
  COUNT(DISTINCT t.id) AS ticket_count,
  SUM(t.stake_amount) AS duplicated_ticket_stake,
  SUM(COALESCE(t.actual_payout, 0)) AS ticket_actual_payout,
  SUM(COALESCE(t.profit_loss, 0)) AS ticket_profit_loss
FROM betting_ticket t
JOIN betting_ticket_selection s ON s.ticket_id = t.id
WHERE t.ticket_status IN ('won', 'lost')
GROUP BY s.play_type, s.option_code, s.option_name
ORDER BY ticket_profit_loss DESC;


-- 9) Data quality: betting legs without a linked SP snapshot.
SELECT
  t.id AS ticket_id,
  t.bet_group,
  t.ticket_label,
  s.id AS selection_id,
  s.match_id,
  s.match_num,
  s.play_type,
  s.option_code,
  s.option_name,
  s.selected_sp,
  s.sp_snapshot_time
FROM betting_ticket t
JOIN betting_ticket_selection s ON s.ticket_id = t.id
WHERE s.sp_snapshot_id IS NULL
ORDER BY t.id, s.leg_index;


-- 10) Data quality: matches with tickets but no result yet after scheduled time.
SELECT
  t.id AS ticket_id,
  t.bet_group,
  s.match_num,
  s.match_id,
  m.home_team_name,
  m.away_team_name,
  m.match_time,
  m.match_status,
  m.result_90
FROM betting_ticket t
JOIN betting_ticket_selection s ON s.ticket_id = t.id
LEFT JOIN sporttery_match m ON m.match_id = s.match_id
WHERE m.result_90 IS NULL
ORDER BY m.match_time, t.id;


-- 11) Settled ticket detail: ticket outcome plus each leg outcome.
SELECT
  t.id AS ticket_id,
  t.bet_group,
  t.ticket_label,
  t.ticket_status,
  t.stake_amount,
  t.actual_payout,
  t.profit_loss,
  s.leg_index,
  s.match_num,
  m.home_team_name,
  m.away_team_name,
  m.full_score_90,
  s.play_type,
  s.option_code,
  s.option_name,
  s.selected_sp,
  s.result_status,
  s.actual_result
FROM betting_ticket t
JOIN betting_ticket_selection s ON s.ticket_id = t.id
LEFT JOIN sporttery_match m ON m.match_id = s.match_id
WHERE t.bet_group = :bet_group
ORDER BY t.id, s.leg_index;
