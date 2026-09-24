"""Package standard gzip-MVT MBTiles with XYZ -> TMS row conversion."""
from pathlib import Path
import json
import sqlite3
import zipfile

root = Path(__file__).resolve().parent.parent
public = root / 'public'
out = root / 'output'
out.mkdir(exist_ok=True)
stats = json.loads((public / 'stats.json').read_text())
tilejson = json.loads((public / 'tilejson.json').read_text())
db_path = out / 'paddle-don.mbtiles'
with sqlite3.connect(db_path) as db:
    db.execute('CREATE TABLE IF NOT EXISTS metadata (name TEXT PRIMARY KEY, value TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS tiles (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_data BLOB, PRIMARY KEY (zoom_level, tile_column, tile_row))')
    db.execute('DELETE FROM tiles')
    metadata = {
        'name': 'PADDLE — Don Delta', 'format': 'pbf', 'type': 'baselayer', 'version': '1',
        'description': 'Azov / Yelizavetinskaya vector sample; decorative canopy is not measured tree data.',
        'bounds': ','.join(map(str, stats['bounds'])), 'center': '39.455,47.142,13.4',
        'minzoom': str(stats['minzoom']), 'maxzoom': str(stats['maxzoom']),
        'attribution': '© OpenStreetMap contributors',
        'json': json.dumps({'vector_layers': tilejson['vector_layers']})
    }
    db.executemany('INSERT OR REPLACE INTO metadata VALUES (?,?)', metadata.items())
    for p in (public / 'tiles').glob('*/*/*.pbf.gz'):
        z, x, y = int(p.parent.parent.name), int(p.parent.name), int(p.name.split('.')[0])
        db.execute('INSERT INTO tiles VALUES (?,?,?,?)', (z, x, 2**z-1-y, p.read_bytes()))
    assert db.execute('SELECT count(*) FROM tiles').fetchone()[0] == stats['tiles']
    db.commit()
    assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
with zipfile.ZipFile(out / 'paddle-don-map.zip', 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for p in public.rglob('*'):
        if p.is_file(): archive.write(p, 'public/' + p.relative_to(public).as_posix())
    for name in ['README.md', 'DATA-LICENSE.md', 'verification.json']:
        if (root / name).exists(): archive.write(root / name, name)
print(json.dumps({'mbtiles_bytes': db_path.stat().st_size, 'zip_bytes': (out / 'paddle-don-map.zip').stat().st_size, 'tiles':stats['tiles']}, indent=2))
