"""Lua invoked by RedisCounters; all script keys must share the same cluster slot."""

RECORD_USAGE = """
-- KEYS: usage replay key, monthly spend hash.
-- ARGV: record JSON, replay TTL, spend TTL, integer micro-USD, field-name JSON.
-- Return the first record without refreshing its TTL or incrementing spend twice.
local prior = redis.call('GET', KEYS[1])
if prior then
  return {prior, 0}
end
local fields = cjson.decode(ARGV[5])
-- Redis serializes the whole script against other commands. Inputs and key types
-- must be valid: a runtime error does not roll back earlier script writes.
for _, field in ipairs(fields) do
  redis.call('HINCRBY', KEYS[2], field, ARGV[4])
end
if #fields > 0 then
  -- Sliding retention is for the monthly hash, separate from the replay window.
  redis.call('EXPIRE', KEYS[2], ARGV[3])
end
-- Unknown-cost records have no fields but still finalize this replay identity.
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return {ARGV[1], 1}
"""
