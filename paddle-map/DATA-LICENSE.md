# Данные и лицензии

Географические данные: © OpenStreetMap contributors, ODbL 1.0.
https://www.openstreetmap.org/copyright
https://opendatacommons.org/licenses/odbl/1-0/

Набор производных геоданных (MVT/MBTiles) распространяется с условиями ODbL.
Сохраняйте атрибуцию OpenStreetMap в интерфейсе и документации и выполняйте
требования лицензии при распространении производной базы.

Источник: Overpass API, endpoint и timestamp исходной базы записаны в
`data/source.json` и `public/stats.json`. Скрипт преобразования доступен в
`scripts/build-tiles.mjs`; исходный запрос — `data/query.overpass`.

Glyph PBF Noto Sans Regular получены из https://github.com/maplibre/demotiles
(https://demotiles.maplibre.org/font/). Лицензия SIL Open Font License 1.1
сохранена в `public/fonts/LICENSE.txt`.

Декоративная крона леса сгенерирована алгоритмически только внутри лесных
контуров OSM; она не представляет инвентаризацию деревьев. Растровые снимки,
тайлы чужих коммерческих карт и изображения из пользовательского референса
не включены в набор.

Лицензии используемых библиотек доступны в их пакетах `node_modules` и
репозиториях: MapLibre GL JS (BSD-3-Clause), geojson-vt (ISC), vt-pbf (MIT),
osmtogeojson (MIT), React (MIT), Phosphor Icons (MIT).
