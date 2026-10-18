# Assault-Cube-Maps
These maps are used to play assaultcube. They are not really good, so i need your help to make them more wonderful. If you have (some) map(s) and you want to put it in this repo, i will be very gratèul about it

## Tools
`tools/optimize_map.py` optimizes a map (format 9 `.cgz`) for rendering speed without changing how it looks or plays:
it sets the textures of wall faces that can never be seen so the engine can merge more cubes into larger mip blocks
(the same idea as the in-game `/savemapoptimised`), and drops exact duplicate entities.

```
python3 tools/optimize_map.py testing.cgz
```
