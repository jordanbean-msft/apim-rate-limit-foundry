REPLACE_PROJECTION = """
redis.call('DEL', KEYS[1])
local values = cjson.decode(ARGV[1])
for key, value in pairs(values) do
  redis.call('HSET', KEYS[1], key, tostring(value))
end
redis.call('HSET', KEYS[1], 'ready', '1')
return 'OK'
"""
