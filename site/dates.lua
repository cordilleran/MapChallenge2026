-- {{< dates >}}: the page's "Posted … · Revised …" line, from data/dates.json (written by page_dates.py).
local cache = nil

local function load()
  if cache then return cache end
  local f = io.open(quarto.project.directory .. "/data/dates.json", "r")
  if not f then
    quarto.log.warning("dates: data/dates.json not found; run site/page_dates.py")
    cache = {}
    return cache
  end
  cache = quarto.json.decode(f:read("a"))
  f:close()
  return cache
end

return {
  ["dates"] = function(args, kwargs, meta)
    local page = pandoc.path.filename(quarto.doc.input_file)
    local e = load()[page]
    if not e then
      quarto.log.warning("dates: no entry for " .. page .. "; run site/page_dates.py")
      return pandoc.Null()
    end
    local s = 'Posted <time datetime="' .. e.posted .. '">' .. e.posted_text .. '</time>'
    if e.revised ~= e.posted then
      s = s .. ' · Revised <time datetime="' .. e.revised .. '">' .. e.revised_text .. '</time>'
    end
    return pandoc.RawBlock("html", '<p class="dates">' .. s .. '</p>')
  end
}
