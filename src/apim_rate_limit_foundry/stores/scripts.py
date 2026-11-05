RESERVE = """
if redis.call('HGET', KEYS[1], 'ready') ~= '1' then return redis.error_reply('RECOVERY_REQUIRED') end
local existing = redis.call('HGET', KEYS[1], 'r:' .. ARGV[1])
if existing then
  local old = cjson.decode(existing)
  if old.fingerprint ~= ARGV[2] then return redis.error_reply('CONFLICT') end
  return cjson.encode(old.decision)
end
local debits = cjson.decode(ARGV[3])
local decision = cjson.decode(ARGV[4])
local allowed = true
local remaining = 9000000000000
local denied = {}
local matched = {}
local by_policy = {}
local blocked_reset = ''
for _, d in ipairs(debits) do
  local count = tonumber(redis.call('HGET', KEYS[1], 'c:' .. d.key) or '0')
  table.insert(matched, d.policy_id)
  if count + d.amount > d.limit then
    allowed = false
    table.insert(denied, d.policy_id)
    if d.reset_at > blocked_reset then blocked_reset = d.reset_at end
  end
end
for _, d in ipairs(debits) do
  local count = tonumber(redis.call('HGET', KEYS[1], 'c:' .. d.key) or '0')
  if allowed then
    count = count + d.amount
    redis.call('HSET', KEYS[1], 'c:' .. d.key, tostring(count))
  end
  remaining = math.min(remaining, d.limit - count)
  by_policy[d.policy_id] = math.max(0, d.limit - count)
end
decision.allowed = allowed
decision.remaining = math.max(0, remaining)
decision.reason = allowed and 'reserved' or 'budget_exhausted'
decision.matched_policy_ids = matched
decision.remaining_by_policy = by_policy
if allowed then
  decision.denied_policy_ids = nil
else
  decision.denied_policy_ids = denied
  decision.reset_at = blocked_reset
end
local saved = {fingerprint=ARGV[2], decision=decision, debits=allowed and debits or {}, final=''}
redis.call('HSET', KEYS[1], 'r:' .. ARGV[1], cjson.encode(saved))
return cjson.encode(decision)
"""

FINALIZE = """
if redis.call('HGET', KEYS[1], 'ready') ~= '1' then return redis.error_reply('RECOVERY_REQUIRED') end
local raw = redis.call('HGET', KEYS[1], 'r:' .. ARGV[1])
if not raw then return redis.error_reply('CONFLICT') end
local old = cjson.decode(raw)
if not old.decision.allowed then return redis.error_reply('CONFLICT') end
if old.final ~= '' then
  if old.final ~= ARGV[3] then return redis.error_reply('CONFLICT') end
  return raw
end
local debits = cjson.decode(ARGV[2])
if #old.debits ~= #debits then return redis.error_reply('CONFLICT') end
for i, before in ipairs(old.debits) do
  if before.key ~= debits[i].key then return redis.error_reply('CONFLICT') end
end
for i, before in ipairs(old.debits) do
  redis.call('HINCRBY', KEYS[1], 'c:' .. before.key, debits[i].amount - before.amount)
end
old.debits = debits
old.final = ARGV[3]
redis.call('HSET', KEYS[1], 'r:' .. ARGV[1], cjson.encode(old))
return cjson.encode(old)
"""

BEGIN_RECOVERY = """
local now = tonumber(redis.call('TIME')[1])
local expiry = tonumber(redis.call('HGET', KEYS[1], 'recovering_until') or '0')
if redis.call('HGET', KEYS[1], 'recovering') and expiry > now then
  return redis.error_reply('CONFLICT')
end
redis.call('HDEL', KEYS[1], 'ready')
redis.call('HSET', KEYS[1], 'recovering', ARGV[1])
redis.call('HSET', KEYS[1], 'recovering_until', tostring(now + 300))
return ARGV[1]
"""

RECOVER = """
if redis.call('HGET', KEYS[1], 'recovering') ~= ARGV[1] then return redis.error_reply('CONFLICT') end
local records = cjson.decode(ARGV[2])
redis.call('DEL', KEYS[1])
for _, record in ipairs(records) do
  redis.call('HSET', KEYS[1], 'r:' .. record.id, cjson.encode(record.counter))
  for _, d in ipairs(record.counter.debits) do
    redis.call('HINCRBY', KEYS[1], 'c:' .. d.key, d.amount)
  end
end
redis.call('HSET', KEYS[1], 'ready', '1')
return 'OK'
"""
