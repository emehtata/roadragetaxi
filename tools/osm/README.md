# OSM tools

## Finland startup minimap

Regenerate the Godot city-selection map from the local Finland PBF:

```bash
python tools/osm/build_finland_minimap.py \
  src/theroadragetrip/assets/osm/finland-latest.osm.pbf \
  godot/finland_minimap.svg
```

The small SVG contains Finland's coastline plus `motorway`, `trunk`, and
`primary` roads; city markers come from the current configured city catalog at runtime.

## OpenStreetMap attribution

The generated map is derived from OpenStreetMap data. Distribution and use
must comply with the OpenStreetMap Open Database License (ODbL), including its
attribution and share-alike requirements where applicable. The generated data
is not added to this repository automatically.
