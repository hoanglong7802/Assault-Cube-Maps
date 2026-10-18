# Assault-Cube-Maps
These maps are used to play assaultcube. They are not really good, so i need your help to make them more wonderful. If you have (some) map(s) and you want to put it in this repo, i will be very gratèul about it

## Tools
`tools/optimize_map.py` optimizes a map (format 9 `.cgz`) for rendering speed without changing how it looks or plays:
it sets the textures of wall faces that can never be seen so the engine can merge more cubes into larger mip blocks
(the same idea as the in-game `/savemapoptimised`), and drops exact duplicate entities.

```
python3 tools/optimize_map.py testing.cgz
```

### Lite version for weak machines
`testing_lite.cgz` is the same map with fewer decoration models: the row of model #103 along the left and right
border walls is thinned from 170 to 74 copies (one every ~6 cubes instead of ~3), so 216 mapmodels become 120.
The map is wide open, so the engine can't hide anything behind walls and draws every model in view;
cutting them is the biggest FPS gain available without changing the layout. Terrain, spawns, items, flags and lights
are identical to `testing.cgz`.

To use it, copy your `testing.cfg` (textures and mapmodels) to `testing_lite.cfg` next to the map.
To make a lite version of another map: `python3 tools/optimize_map.py --lite mymap.cgz mymap_lite.cgz`.
