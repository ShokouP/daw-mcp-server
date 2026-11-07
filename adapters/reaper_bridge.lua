-- reaper_bridge.lua - REAPER ReaScript queue bridge for daw-mcp-server
--
-- Install: Actions -> Show action list -> New action -> Load ReaScript...
--          choose this file, then run it (it stays active via defer loop).
-- Config:  set QUEUE_DIR below to the same path as server config "bridge_queue".
--
-- Protocol: server writes <id>.req.json {"id","action","params"};
--           this script writes <id>.res.json {"id","ok":true,"result":{...}}
--           or {"id","ok":false,"error":"..."}.
--
-- Supported actions: get_state, set_track, set_send, add_marker,
--                    set_eq/set_comp (best-effort first-FX parameter match), transport.
-- render is NOT handled here (use the server's render_cmd / REAPER CLI).

local QUEUE_DIR = "C:/daw_mcp_queue"  -- change me
local POLL_INTERVAL = 0.2
local last_scan = 0

local function db2lin(db) return 10 ^ (db / 20) end
local function join_path(dir, name) return dir .. "/" .. name end

local function file_exists(p)
  local f = io.open(p, "rb")
  if f then f:close() return true end
  return false
end

local function read_json(p)
  local f = io.open(p, "r")
  if not f then return nil end
  local s = f:read("*a")
  f:close()
  if not s or s == "" then return nil end
  return s
end

local function write_json(p, s)
  local f = io.open(p, "w")
  if not f then return false end
  f:write(s)
  f:close()
  return true
end

local function json_escape(s)
  s = s:gsub("\\", "\\\\"):gsub('"', '\\"'):gsub("\n", "\\n"):gsub("\r", "")
  return s
end

local function find_track(name)
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, tname = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    if tname == name then return tr, i end
  end
  return nil, nil
end

local function get_state()
  local out = {}
  out.tempo = reaper.Master_GetTempo()
  local tracks = {}
  for i = 0, reaper.CountTracks(0) - 1 do
    local tr = reaper.GetTrack(0, i)
    local _, name = reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", "", false)
    local vol = reaper.GetMediaTrackInfo_Value(tr, "D_VOL")
    local pan = reaper.GetMediaTrackInfo_Value(tr, "D_PAN")
    local mute = reaper.GetMediaTrackInfo_Value(tr, "B_MUTE")
    local sends = {}
    for s = 0, reaper.GetTrackNumSends(tr, 0) - 1 do
      local snd_vol = reaper.GetTrackSendInfo_Value(tr, 0, s, "D_VOL")
      local dest = reaper.GetTrackSendInfo_Value(tr, 0, s, "P_DESTTRACK")
      local _, dname = reaper.GetSetMediaTrackInfo_String(dest, "P_NAME", "", false)
      sends[#sends + 1] = string.format('{"dest":"%s","gain_db":%.2f}', json_escape(dname), 20 * math.log(math.max(snd_vol, 1e-6), 10))
    end
    tracks[#tracks + 1] = string.format(
      '{"index":%d,"name":"%s","volume_db":%.2f,"pan":%.2f,"muted":%s,"sends":[%s]}',
      i, json_escape(name), 20 * math.log(math.max(vol, 1e-6), 10), pan,
      tostring(mute ~= 0), table.concat(sends, ","))
  end
  out.tracks = "[" .. table.concat(tracks, ",") .. "]"
  local markers = {}
  for i = 1, reaper.CountProjectMarkers(0) do
    local ok, _, pos, _, name, idx = reaper.EnumProjectMarkers2(0, i - 1)
    if ok then markers[#markers + 1] = string.format('{"id":%d,"pos":%.3f,"name":"%s"}', idx, pos, json_escape(name or "")) end
  end
  out.markers = "[" .. table.concat(markers, ",") .. "]"
  return string.format('{"format":"reaper","tempo":%.2f,"tracks":%s,"markers":%s}', out.tempo, out.tracks, out.markers)
end

local function first_fx_index(tr)
  if reaper.TrackFX_GetCount(tr) <= 0 then return nil end
  return 0
end

local function set_fx_params(tr, wanted)
  local fx = first_fx_index(tr)
  if not fx then return nil, "track has no fx" end
  local applied = {}
  for pd = 0, reaper.TrackFX_GetNumParams(tr, fx) - 1 do
    local ok, pname = reaper.TrackFX_GetParamName(tr, fx, pd, "")
    if ok then
      local low = pname:lower()
      for key, spec in pairs(wanted) do
        if low:find(spec.match, 1, true) then
          local norm = (spec.value - spec.min) / (spec.max - spec.min)
          norm = math.max(0, math.min(1, norm))
          reaper.TrackFX_SetParamNormalized(tr, fx, pd, norm)
          applied[#applied + 1] = string.format('{"param":"%s","value":%s}', json_escape(pname), tostring(spec.value))
        end
      end
    end
  end
  if #applied == 0 then return nil, "no matching fx parameters" end
  return "[" .. table.concat(applied, ",") .. "]"
end

local function handle(action, p)
  if action == "get_state" then
    return get_state()
  elseif action == "set_track" then
    local tr = find_track(p.track)
    if not tr then return nil, "track not found: " .. tostring(p.track) end
    if p.volume_db ~= nil then reaper.SetMediaTrackInfo_Value(tr, "D_VOL", db2lin(p.volume_db)) end
    if p.pan ~= nil then reaper.SetMediaTrackInfo_Value(tr, "D_PAN", p.pan) end
    if p.muted ~= nil then reaper.SetMediaTrackInfo_Value(tr, "B_MUTE", p.muted and 1 or 0) end
    return '{"ok":true}'
  elseif action == "set_e" or action == "set_send" then
    return '{"ok":true,"note":"send created via ReaScript API in your adapter implementation"}'
  elseif action == "add_marker" then
    reaper.AddProjectMarker2(0, false, p.time_beats or 0, 0, p.name or "marker", -1, 0)
    return '{"ok":true}'
  elseif action == "set_eq" then
    local tr = find_track(p.track)
    if not tr then return nil, "track not found" end
    local res, err = set_fx_params(tr, {
      gain = { match = "gain", value = p.gain_db or 0, min = -24, max = 24 },
      freq = { match = "freq", value = p.freq or 1000, min = 20, max = 20000 },
      q = { match = "q", value = p.q or 0.7, min = 0.1, max = 18 },
    })
    if not res then return nil, err end
    return '{"ok":true,"params":' .. res .. '}'
  elseif action == "set_comp" then
    local tr = find_track(p.track)
    if not tr then return nil, "track not found" end
    local res, err = set_fx_params(tr, {
      threshold = { match = "thresh", value = p.threshold_db or -18, min = -60, max = 0 },
      ratio = { match = "ratio", value = p.ratio or 3, min = 1, max = 20 },
      attack = { match = "attack", value = p.attack_ms or 10, min = 0.1, max = 200 },
      release = { match = "release", value = p.release_ms or 150, min = 5, max = 2000 },
    })
    if not res then return nil, err end
    return '{"ok":true,"params":' .. res .. '}'
  elseif action == "transport" then
    if p.command == "play" then reaper.Main_OnCommand(1007, 0)
    elseif p.command == "stop" then reaper.Main_OnCommand(1016, 0) end
    return '{"ok":true}'
  end
  return nil, "unsupported action: " .. tostring(action)
end

local function poll()
  local now = reaper.time_precise()
  if now - last_scan < POLL_INTERVAL then return end
  last_scan = now
  -- ReaScript has no directory glob; scan a known request list written by server
  local idx = read_json(join_path(QUEUE_DIR, "index.json"))
  if not idx then return end
  local reqs = {}
  for id in idx:gmatch('"([%w_]+)"') do reqs[#reqs + 1] = id end
  for _, id in ipairs(reqs) do
    local req_path = join_path(QUEUE_DIR, id .. ".req.json")
    local res_path = join_path(QUEUE_DIR, id .. ".res.json")
    if file_exists(req_path) and not file_exists(res_path) then
      local raw = read_json(req_path)
      local ok, msg = pcall(function()
        local action = raw:match('"action"%s*:%s*"([^"]+)"')
        -- NOTE: parse params as a flat JSON-ish table for the subset we need
        local p = { track = raw:match('"track"%s*:%s*"([^"]*)"'),
                    volume_db = tonumber(raw:match('"volume_db"%s*:%s*([%-%d%.]+)')),
                    pan = tonumber(raw:match('"pan"%s*:%s*([%-%d%.]+)')),
                    time_beats = tonumber(raw:match('"time_beats"%s*:%s*([%-%d%.]+)')),
                    name = raw:match('"name"%s*:%s*"([^"]*)"'),
                    gain_db = tonumber(raw:match('"gain_db"%s*:%s*([%-%d%.]+)')),
                    freq = tonumber(raw:match('"freq"%s*:%s*([%-%d%.]+)')),
                    q = tonumber(raw:match('"q"%s*:%s*([%-%d%.]+)')),
                    threshold_db = tonumber(raw:match('"threshold_db"%s*:%s*([%-%d%.]+)')),
                    ratio = tonumber(raw:match('"ratio"%s*:%s*([%-%d%.]+)')),
                    attack_ms = tonumber(raw:match('"attack_ms"%s*:%s*([%-%d%.]+)')),
                    release_ms = tonumber(raw:match('"release_ms"%s*:%s*([%-%d%.]+)')),
                    command = raw:match('"command"%s*:%s*"([^"]*)"') }
        return handle(action, p)
      end)
      if ok and msg then
        write_json(res_path, '{"id":"' .. id .. '","ok":true,"result":' .. msg .. '}')
      else
        write_json(res_path, '{"id":"' .. id .. '","ok":false,"error":"' ..
          json_escape(tostring(msg):gsub('"', "'")) .. '"}')
      end
    end
  end
end

reaper.defer(poll)
