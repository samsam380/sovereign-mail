#!/usr/bin/env python3
"""Create an offline, sample-data-only HTML preview. Never use for real mail."""
from pathlib import Path
import base64
root=Path(__file__).resolve().parents[1]
static=root/'app/static'
html=(static/'index.html').read_text()
css=(static/'app.css').read_text()
js=(static/'app.js').read_text().replace("config=await http('/api/config');", "config={demo:true,domain:'example.com'};")
svg='data:image/svg+xml;base64,'+base64.b64encode((static/'mark.svg').read_bytes()).decode()
html=html.replace('/mark.svg',svg)
html=html.replace('<link rel="stylesheet" href="/app.css">','<style>'+css+'</style>')
html=html.replace('<script type="module" src="/app.js"></script>','<script type="module">'+js.replace('</script','<\\/script')+'</script>')
html=html.replace('href="/" aria-label="Sovereign Mail home"','href="#" aria-label="Sovereign Mail home"')
html=html.replace('<title>Sovereign Mail</title>','<title>Sovereign Mail · Offline Preview</title>')
# No network requests are needed. Production uses an external-script CSP instead.
html=html.replace('<meta charset="UTF-8">','<meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; connect-src \'none\'; object-src \'none\'; frame-src \'none\'; base-uri \'none\'; form-action \'none\'">')
(root/'Sovereign-Mail-Preview.html').write_text(html)
print('Built offline sample-data preview.')
