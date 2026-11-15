#!/usr/bin/env python3
"""Audit-only inventory, multi-angle contact sheets and evidence consistency checks.

    .venv/bin/python tools/visual_quality_audit.py --capture
    .venv/bin/python tools/visual_quality_audit.py --check

Production assets/builders are read, never edited. The capture process is bounded.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import tempfile

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs/visual-quality-audit"
ANGLES = ["front", "rear", "left", "right", "front_three_quarter", "rear_three_quarter", "top", "elevated"]
STATUSES = {"passed", "defects", "partially inspected", "uninspected", "unused/not reachable"}


def summary(data):
    counts = Counter(a["status"] for a in data["assets"])
    return {"discovered": len(data["assets"]), "inspected": sum(a["status"] in {"passed", "defects", "partially inspected"} for a in data["assets"]),
            "statuses": dict(sorted(counts.items())), "assets_with_defects": len({d["asset"] for d in data["defects"]}),
            "defects_by_severity": dict(Counter(d["severity"] for d in data["defects"])),
            "defects_by_category": dict(Counter(d["category"] for d in data["defects"]))}


def validate_runtime(manifest, root):
    errors = []
    for capture in manifest['captures']:
        if not (root / capture['file']).is_file(): errors.append(f"missing {capture['file']}")
        if not capture.get('ready'): errors.append(f"{capture['file']}: readiness failed")
    for home in manifest.get('homes', []):
        if home.get('completed') is False: errors.append(f"{home['asset']}: room route did not complete")
        if len(set(home['rooms_visited'])) != home['rooms_expected']:
            errors.append(f"{home['asset']}: rooms not all traversed")
        if len(set(home['doors_crossed'])) != home['doors_expected']:
            errors.append(f"{home['asset']}: doors not all crossed")
    sampled = {(row['asset'], row['system']) for row in manifest.get('lod', [])}
    for row in manifest.get('lod_expected', []):
        if (row['asset'], row['system']) not in sampled:
            errors.append(f"{row['asset']}: LOD not sampled: {row['system']}")
    return errors


def validate_gap_matrix(matrix, root):
    errors = []
    for family in matrix['families']:
        if family['status']=='completed':
            for state in set(family.get('expected_states', [])) - set(family.get('captured_states', [])):
                errors.append(f"{family['id']}: state not captured: {state}")
        if family['status']=='completed' and not family.get('evidence'):
            errors.append(f"{family['id']}: completed family lacks capture evidence")
        if not family.get('source'): errors.append(f"{family['id']}: source missing")
        for path in family.get('evidence', []):
            if not (root/path).is_file(): errors.append(f"{family['id']}: missing {path}")
        if family['status'] in ['unavailable','still unverified'] and not family.get('reason'):
            errors.append(f"{family['id']}: gap reason missing")
    return errors


def validate(data, root):
    errors = []
    ids = [a["id"] for a in data["assets"]]
    if len(set(ids)) != len(ids): errors.append("duplicate asset IDs")
    defect_ids = [d["id"] for d in data["defects"]]
    if len(set(defect_ids)) != len(defect_ids): errors.append("duplicate defect IDs")
    for a in data["assets"]:
        for field in ("id", "name", "category", "source", "status"):
            if not a.get(field): errors.append(f"{a.get('id')}: missing {field}")
        if a["status"] not in STATUSES: errors.append(f"{a['id']}: invalid status")
        views = set()
        for e in a.get("evidence", []):
            views.update(e.get("angles", []))
            if not (root / e["file"]).is_file(): errors.append(f"{a['id']}: missing {e['file']}")
            if not e.get("ready", False): errors.append(f"{a['id']}: evidence readiness missing")
            if e.get("capture_kind") == "targeted context" and not e.get("target_confirmed"):
                errors.append(f"{a['id']}: context target identification missing")
        if a["status"] == "passed" and len(views) < 2:
            errors.append(f"{a['id']}: a pass requires multiple views")
        if a["status"] == "passed" and a.get("mode") not in (None, "2d") and not set(ANGLES).issubset(views):
            errors.append(f"{a['id']}: missing required 3D angles")
        if a["status"] in {"uninspected", "partially inspected", "unused/not reachable"} and not a.get("reason"):
            errors.append(f"{a['id']}: limitation reason missing")
        if a["status"] == "defects" and not any(d.get("asset") == a["id"] for d in data["defects"]):
            errors.append(f"{a['id']}: defect status without a defect")
    for d in data["defects"]:
        if d.get("asset") not in ids: errors.append(f"{d['id']}: unknown asset {d.get('asset')}")
        for field in ("severity", "category", "angle", "condition", "description", "file", "source", "panel"):
            if not d.get(field): errors.append(f"{d['id']}: missing {field}")
        if d.get("severity") not in {"Critical", "High", "Medium", "Low"}: errors.append(f"{d['id']}: invalid severity")
        if d.get("file") and not (root / d["file"]).is_file(): errors.append(f"{d['id']}: missing evidence")
    if "summary" in data and data["summary"] != summary(data): errors.append("summary does not reconcile with inventory")
    return errors


def inventory():
    assets = []
    def add(category, name, mode, kind, source="godot/buildings_3d.gd", **extra):
        assets.append(dict(id=f"A-{len(assets)+1:03}", category=category, name=name, mode=mode, kind=kind,
                           source=source, status="uninspected", evidence=[], reason="capture pending", **extra))
    sizes = {"saloon": (4.4,1.8), "hatchback": (3.9,1.7), "estate": (4.8,1.9), "suv": (4.8,1.9),
             "pickup": (5,1.9), "sports": (4.7,1.8), "city_car": (3.8,1.7), "panel_van": (5.1,2),
             "box_truck": (8,2.5), "motorcycle": (2.1,.8), "city_bus": (10,2.5), "camper_van": (6,2.2),
             "tractor": (4,2), "caravan": (5,2.1), "e_scooter": (1.3,.5), "e_scooter_grab3d": (1.3,.5),
             "bicycle": (1.8,.6), "mountain_bike": (1.8,.6), "train_locomotive": (19,3.2), "train_coach": (24,3.2),
             "tram": (9.2,2.4), "ferry": (32,10)}
    for kind, (length,width) in sizes.items():
        add("Vehicles", kind, "vehicle", kind, length=length,width=width)
    for kind in ("motorcycle", "bicycle", "e_scooter"):
        add("Vehicles", kind+" with rider", "vehicle", kind,length=sizes[kind][0],width=sizes[kind][1],extra={"riding":True})
    add("Vehicles","tractor with plough and beacon","vehicle","tractor",length=4,width=2,extra={"plough":True,"beacon":True})
    for name, lamps, sign in [("taxi roof sign",1,2),("brake lights",3,0),("reverse lights",5,0),("left indicator",9,0),("right indicator",17,0)]:
        add("Vehicles",name,"vehicle","saloon",length=4.4,width=1.8,lamps=lamps,sign=sign)
    for variant in range(8): add("People",f"clothing/body variant {variant}","person","person",variant=variant)
    for pose in ("walk_1","run_2","sitting","swimming","riding","standing_1"):
        add("People",pose,"person","person",pose=pose)
    for costume in ("santa","elf"): add("People",costume,"person","person",costume=costume)
    for beard in (2,3,5): add("People",f"beard {beard}","person","person",beard=beard)
    add("People","winter jacket","person","person",winter=True)
    add("People","shopper with cart","person","person",cart=True)
    add("People","distant person detail 0","person","person",detail=0)
    for kind in ("fox","small_bird","roe_deer","horse","hare","squirrel","pigeon","moose","crow","duck","gull","dog"):
        add("Animals",kind,"animal",kind)
    for kind,pose in (("crow","fly_1"),("gull","fly_0"),("dog","feed"),("moose","walk_a")):
        add("Animals",kind+" "+pose,"animal",kind,pose=pose)
    for kind in ("spruce","pine","birch","shrub"):
        add("Vegetation",kind,"tree",kind)
    for kind in ("spruce","pine","birch"):
        add("Vegetation",kind+" far","tree",kind,far=True)
    add("Vegetation","felled tree","tree","birch",felled=True)
    text = (REPO/"godot/buildings_3d.gd").read_text()
    props = text.split("const PROPS :=",1)[1].split("const GAP_KINDS",1)[0]
    for kind in re.findall(r'"(\w+)":\s*\[',props): add("Props",kind,"prop",kind)
    add("Props","bench without backrest","prop","bench",no_backrest=True)
    for kind in ("roller_coaster","drop_tower","carousel","swing_carousel","ferris_wheel"):
        add("Attractions",kind,"attraction",kind)
    for kind in ("biergarten","cemetery"): add("Sites",kind,"site",kind)
    landmarks=json.loads((REPO/"src/theroadragetrip/assets/landmarks.json").read_text())
    for kind,spec in landmarks.items():
        if not kind.startswith("_"): add("Landmarks",kind,"landmark",kind,source="src/theroadragetrip/assets/landmarks.json",spec=spec)
    for name,opts in [("apartment",{}),("house",{"category_id":1,"height":6,"floors":2}),
                      ("commercial",{"category_id":2}),("plain wall",{"category_id":3}),
                      ("retail hall",{"category_id":4}),("wood cabin",{"category_id":5,"height":4,"floors":1,"roof":1}),
                      ("gabled",{"roof":1}),("steep church roof",{"roof":2}),
                      ("glasshouse",{"special":2}),("gabled glasshouse",{"special":2,"roof":1}),
                      ("arena facade",{"special":1}),("tall block",{"height":45,"floors":15}),
                      ("concave",{})]:
        add("Buildings",name,"building",name,**opts)
    add("Construction","tower crane","crane","crane")
    add("Construction","live roadwork cone","cone","cone")
    add("Construction","live roadwork barrier","barrier","barrier")
    add("Infrastructure","street lamp","lamp","lamp")
    add("Infrastructure","bollard","bollard","bollard")
    for kind in ("red","yellow","green"): add("Infrastructure","traffic signal "+kind,"signal",kind)
    for kind in ("hedge","wall","fence","boards"): add("Infrastructure",kind,"railing",kind)
    for kind in ("road","water","parking","landuse","rail","bus_bay","crossing","bump","island","curb","puddle","foam"):
        add("Ground",kind,"ground",kind)
    for surface,name in enumerate(("asphalt","paving","sett","cobblestone","gravel","concrete","wood","grass paver"),1):
        add("Ground",name+" surface","ground","road",surface=surface)
    for kind in ("bridge","guardrail","rail_bridge","pier","canopy","site_fence","shelter","stop_bench","net","sign_post","pump","power_line"):
        add("Structures",kind,"structure",kind)
    plans=json.loads((REPO/"godot/tests/data/home_plans.json").read_text())
    for i in range(len(plans)): add("Interiors",f"home plan {i}","interior","home",source="godot/home_interior_3d.gd",index=i)
    # Additional live render paths are listed explicitly rather than silently passed by a generic scene.
    extras = {
      "Map overlays": ("godot/chunk_detail.gd", ["parking bay markings","disabled parking icon","taxi stand sign","stop sign","speed limit sign","speed camera","bus stop sign","fuel price board","volleyball court","tennis court","soccer pitch","ice hockey rink","golf course","wetland reeds","track markings","canopy feet","building entrance mark"]),
      "Effects": ("godot/entity_layer.gd",["exhaust smoke","engine smoke","tyre tracks","vomit puddle","vomit splashes","headlight beams","brake glow","taxi sign glow","puck","soccer ball","golf ball","hockey stick","golf club","dog leash","bottle","speech bubble","rage face","booked passenger arrow"]),
      "Weather": ("godot/weather_layer.gd",["rain","snow","slush","water ripples","vehicle splash","mud overlay","lightning"]),
      "Seasonal": ("godot/holiday_layer.gd",["Christmas eave lights","Christmas star","flags","bonfire","ghost","fireworks"]),
      "Water states": ("godot/map_chunk.gd",["ice floe","shore waves","open water shader","ice cover","waterline"]),
      "Interface": ("godot/main.gd",["HUD","phone","navigation phone","taxi meter","startup menus","map browser","date picker","tutorial","electronic sign","door interaction marker","route ribbon","floating map labels","loading screen","pause and settings"]),
      "Interior furniture": ("godot/home_interior.gd",sorted({f["kind"] for p in plans for f in p.get("furniture",[])})),
    }
    for category,(source,names) in extras.items():
        for name in names:
            add(category,name,"uninspected",name,source=source)
            assets[-1]["reason"]="Contextual 2D/state-driven renderer: isolated 3D sheets do not exercise this draw path; gameplay coverage must identify the exact object/state."
    registered=set(sizes)|{"train","bus","truck","trailer"}
    for p in sorted((REPO/"godot/assets/vehicles").glob("*.glb")):
        if p.stem not in registered:
            add("Unused assets",p.stem,"uninspected",p.stem,source=str(p.relative_to(REPO)))
            assets[-1].update(status="unused/not reachable",reason="GLB is not registered in MODEL_SCENES/MODEL_VARIANTS; its import alone does not make it visible in gameplay.")
    for category,name,source in [("Map overlays","yield sign","godot/chunk_detail.gd"),("Seasonal","Halloween lanterns","godot/holiday_layer.gd")]:
        add(category,name,"uninspected",name,source=source)
        assets[-1]["reason"]="Supplemental canvas capture pending."
    return correct_inventory({"assets":assets,"defects":[],"conditions":["day","overcast","night"]})


def correct_inventory(data):
    absent = {"A-209": "disabled parking icon", "A-220": "separate golf-course overlay", "A-224": "separate building entrance mark"}
    data["absent_categories"] = [{"name": name, "former_id": id_, "evidence": "Source search across godot/*.gd and *.gdshader found no dedicated draw method; golf landuse and physical building doors use already inventoried generic renderers.", "searched": ["godot/chunk_detail.gd", "godot/map_chunk.gd", "godot/buildings_3d.gd", "godot/door_marks.gd"]} for id_, name in absent.items()]
    data["assets"] = [a for a in data["assets"] if a["id"] not in absent]
    for a in data["assets"]:
        if a["id"] == "A-250": a["name"] = "Christmas eave lights"
        if a["id"] == "A-251": a["source"] = "godot/building_snow.gdshader"
        if a["id"] == "A-212": a["source"] = "godot/entity_layer.gd"
    return data


def capture_context(data):
    import visual_test
    from PIL import Image, ImageDraw
    godot=visual_test._godot()
    with tempfile.TemporaryDirectory(prefix="rrt-vqa-context-",dir=OUT) as temporary:
        scratch=Path(temporary)
        fixture=scratch/"fixture.json"; fixture.write_text(json.dumps(data))
        command=[str(godot),"--path",visual_test._host_path(REPO/"godot",godot),"--script","res://tools/visual_quality_audit_context.gd","--",visual_test._host_path(fixture,godot),visual_test._host_path(scratch,godot)]
        with (OUT/"context-capture.log").open("w") as log:
            subprocess.run(command,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,timeout=300,check=True)
        if "SCRIPT ERROR" in (OUT/"context-capture.log").read_text():
            raise RuntimeError("context capture script errors; inspect context-capture.log before accepting evidence")
        result=json.loads((scratch/"context-results.json").read_text())
        previous_path=OUT/"context-manifest.json"
        if previous_path.exists():
            previous=json.loads(previous_path.read_text())
            replaced={r["asset"] for r in result["captures"]}
            result["captures"]=[r for r in previous["captures"] if r["asset"] not in replaced]+result["captures"]
        result["source_revision"]=visual_test._commit()
        result["fixtures"]=data
        grouped={}
        for record in result["captures"]:
            if record["ready"] and (scratch/record["file"]).exists(): grouped.setdefault(record["asset"],[]).append(record)
        for a in data["assets"]:
            records=grouped.get(a["id"],[])
            if not records: continue
            filename=f"context_{a['id']}_normal-close.png"
            sheet=Image.new("RGB",(800*len(records),630),"#16212c");draw=ImageDraw.Draw(sheet)
            for i,record in enumerate(records):
                with Image.open(scratch/record["file"]) as im: sheet.paste(im,(800*i,30))
                draw.text((800*i+8,8),f"{a['id']} {a['name']} | {record['angle']}",fill="white")
                record["sheet"]=filename;record["panel"]=i+1
            sheet.save(OUT/filename,optimize=True)
            a["evidence"].append(dict(file=filename,row=1,angles=[r["angle"] for r in records],condition="targeted production draw",ready=True,capture_kind="targeted context",target_confirmed=True))
            a["status"]="partially inspected"
            a["reason"]="Target-specific production draw captured at two states/scales; human review and world integration pending."
        (OUT/"context-manifest.json").write_text(json.dumps(result,indent=2)+"\n")
    return data


def capture(data):
    import visual_test
    godot=visual_test._godot()
    with tempfile.TemporaryDirectory(prefix="rrt-vqa-",dir=OUT) as temporary:
        scratch=Path(temporary)
        fixture=scratch/"fixture.json"
        fixture.write_text(json.dumps(data),encoding="utf-8")
        command=[str(godot),"--path",visual_test._host_path(REPO/"godot",godot),"--script","res://tools/visual_quality_audit.gd"]
        if godot.suffix != ".exe": command += ["--display-driver","x11","--rendering-driver","opengl3"]
        command += ["--",visual_test._host_path(fixture,godot),visual_test._host_path(scratch,godot)]
        with (OUT/"capture.log").open("w") as log:
            subprocess.run(command,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,timeout=1200,check=True)
        canvas_command=list(command)
        canvas_command[canvas_command.index("res://tools/visual_quality_audit.gd")]="res://tools/visual_quality_audit_canvas.gd"
        with (OUT/"canvas-capture.log").open("w") as log:
            subprocess.run(canvas_command,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,timeout=240,check=True)
        compose(data,scratch)
        compose_canvas(data,scratch)
    return data


def compose(data,scratch):
    from PIL import Image, ImageDraw
    import visual_test
    result=json.loads((scratch/"capture-results.json").read_text())
    result["source_revision"]=visual_test._commit()
    result["fixture"]=data
    (OUT/"capture-manifest.json").write_text(json.dumps(result,indent=2)+"\n")
    groups={}
    for a in data["assets"]:
        if a["mode"] != "uninspected": groups.setdefault(a["category"],[]).append(a)
    for category,assets in groups.items():
        for page in range(0,len(assets),4):
            for condition in data["conditions"]:
                rows=assets[page:page+4]
                sheet=Image.new("RGB",(3200,370*len(rows)),"#16212c")
                draw=ImageDraw.Draw(sheet)
                for y,a in enumerate(rows):
                    for x,angle in enumerate(ANGLES):
                        name=f"{a['id']}_{condition}_{angle}.png"
                        with Image.open(scratch/name) as img: sheet.paste(img,(400*x,370*y+30))
                        draw.text((400*x+5,370*y+5),f"{a['id']} {a['name']} | {angle}",fill="white")
                filename=f"{category.lower().replace(' ','_')}_{page//4+1:02}_{condition}_eight-angles.png"
                sheet.save(OUT/filename,optimize=True)
                for y,a in enumerate(rows):
                    a["evidence"].append(dict(file=filename,row=y+1,angles=ANGLES,condition=condition,ready=True))
                    a["status"]="partially inspected"
                    a["reason"]="Eight isolated angles rendered at close distance; pending human image review and gameplay/distance coverage."


def compose_canvas(data,scratch):
    from PIL import Image, ImageDraw
    result=json.loads((scratch/"canvas-results.json").read_text())
    (OUT/"canvas-manifest.json").write_text(json.dumps(result,indent=2)+"\n")
    assets={a["id"]:a for a in data["assets"]}
    rows={}
    for r in result["captures"]:
        if r["ready"]: rows.setdefault(r["asset"],[]).append(r)
    selected=list(rows)
    for start in range(0,len(selected),3):
        ids=selected[start:start+3]
        sheet=Image.new("RGB",(1600,len(ids)*630),"#16212c")
        draw=ImageDraw.Draw(sheet)
        filename=f"canvas_{start//3+1:02}_normal-close.png"
        for y,id_ in enumerate(ids):
            a=assets[id_]
            for x,r in enumerate(rows[id_]):
                with Image.open(scratch/r["file"]) as img: sheet.paste(img,(800*x,630*y+30))
                draw.text((800*x+8,630*y+8),f"{id_} {a['name']} | {r['angle']}",fill="white")
            a["evidence"].append(dict(file=filename,row=y+1,angles=[r["angle"] for r in rows[id_]],condition="canvas fixed palette",ready=True))
            a["status"]="partially inspected"
            a["reason"]="Production canvas draw path captured at two zooms; world occlusion and dynamic state integration remain unverified."
        sheet.save(OUT/filename,optimize=True)


def capture_distance(data):
    import visual_test
    from PIL import Image, ImageDraw
    godot=visual_test._godot()
    with tempfile.TemporaryDirectory(prefix="rrt-vqa-distance-",dir=OUT) as temporary:
        scratch=Path(temporary); fixture=scratch/"fixture.json";fixture.write_text(json.dumps(data))
        command=[str(godot),"--path",visual_test._host_path(REPO/"godot",godot),"--script","res://tools/visual_quality_audit_distance.gd","--",visual_test._host_path(fixture,godot),visual_test._host_path(scratch,godot)]
        with (OUT/"distance-capture.log").open("w") as log:
            subprocess.run(command,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,timeout=900,check=True)
        if "SCRIPT ERROR" in (OUT/"distance-capture.log").read_text(): raise RuntimeError("distance capture script errors")
        result=json.loads((scratch/"distance-results.json").read_text());result["source_revision"]=visual_test._commit();result["fixture"]=data
        for a in data["assets"]:
            for family in ["distance","indoor"]:
                records=[r for r in result["captures"] if r["asset"]==a["id"] and f"_{family}_" in r["file"]]
                if not records: continue
                filename=f"{family}_{a['id']}_perspective.png";sheet=Image.new("RGB",(640*len(records),510),"#16212c");draw=ImageDraw.Draw(sheet)
                for i,r in enumerate(records):
                    with Image.open(scratch/r["file"]) as im:sheet.paste(im,(640*i,30))
                    draw.text((640*i+8,8),f"{a['id']} {a['name']} | {r['angle']} | {r.get('distance_m',1.6):.2f} m",fill="white")
                    r["sheet"]=filename;r["panel"]=i+1
                sheet.save(OUT/filename,optimize=True)
                a["evidence"].append(dict(file=filename,row=1,angles=[r["angle"] for r in records],condition="day perspective sweep" if family=="distance" else "actual indoor first person",ready=True))
        (OUT/"distance-manifest.json").write_text(json.dumps(result,indent=2)+"\n")
    return data


def validate_map_context(result, minimum_m, require_reload=False):
    context = result.get('audit_context', {})
    errors = []
    distance = context.get('travel_m', 0)
    if require_reload and context.get('timeline'):
        import math
        start = context['timeline'][0]['position']
        distance = max(math.dist(start, sample['position']) for sample in context['timeline'])
    if context.get('samples', 0) < 2 or distance < minimum_m:
        errors.append('audit: map context did not cover the requested motion')
    if not context.get('added_chunk_ids') and not context.get('removed_chunk_ids'):
        errors.append('audit: no natural chunk membership change observed')
    if require_reload and not (set(context.get('reloaded_chunk_ids', [])) & set(context.get('removed_chunk_ids', [])) & set(context.get('added_chunk_ids', []))):
        errors.append('audit: no naturally evicted chunk was reloaded on revisit')
    return errors


def capture_gameplay(ids):
    """Existing named scenarios with stricter map-idle checks in an audit-only runner."""
    import datetime as dt
    import os
    import socket
    import visual_test
    failed=False
    for id_ in ids:
        scenario=visual_test.scenarios()[id_].copy()
        start=scenario["start_time"]
        out=OUT/"gameplay_strict"/id_/f"{dt.datetime.now():%Y%m%d-%H%M%S}_{visual_test._commit()}"
        out.mkdir(parents=True)
        scenario.update(commit=visual_test._commit(),audit_readiness="production readiness plus server map_loading empty and HUD banner hidden")
        (out/"scenario.json").write_text(json.dumps(scenario,indent=2))
        x,y,heading=scenario["pose"]
        with socket.socket() as sock:
            sock.bind(("127.0.0.1",0));port=sock.getsockname()[1]
        server_args=["--port",str(port),"--preset",scenario["city"],"--bbox",visual_test._bbox(x,y,scenario.get("box_km",2.0)),"--start-time",start,"--test-pose",f"{x},{y},{heading}","--test-weather",scenario["weather"],"--test-cloud",str(scenario["cloud"]),"--test-seed",str(scenario.get("seed",1)),"--test-time-scale","0","--no-historical-weather","--no-intercity-fares",*scenario.get("server_args",[])]
        with (out/"server.log").open("w") as log:
            server=subprocess.Popen([str(REPO/".venv/bin/python"),"-m","theroadragetrip.server",*server_args],cwd=REPO,stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,PYTHONPATH="src"))
            try:
                subprocess.run([str(REPO/".venv/bin/python"),"tools/wait_for_port.py","127.0.0.1",str(port),"300"],cwd=REPO,check=True,timeout=310)
                godot=visual_test._godot()
                command=[str(godot),"--path",visual_test._host_path(REPO/"godot",godot),"--script","res://tools/visual_quality_audit_gameplay.gd","--","--port",str(port),"--zoom",str(scenario.get("zoom",1)),"--audit-scenario",visual_test._host_path(out/"scenario.json",godot),*scenario.get("godot_args",[])]
                with (out/"godot.log").open("w") as client_log:
                    subprocess.run(command,cwd=REPO,stdout=client_log,stderr=subprocess.STDOUT,timeout=310,check=False)
            finally:
                server.terminate()
                try: server.wait(10)
                except subprocess.TimeoutExpired:server.kill();server.wait()
        result=json.loads((out/"result.json").read_text())
        if scenario.get('audit_context') and result['status'] == 'passed':
            errors = validate_map_context(result, scenario.get('audit_motion_m', 50), scenario.get('audit_chunk_revisit', False))
            if errors:
                result.update(status='failed', errors=errors)
                (out/'result.json').write_text(json.dumps(result, indent=2)+'\n')
        failed=failed or result["status"]!="passed"
        print(json.dumps({"scenario":id_,"status":result["status"],"errors":result.get("errors",[]),"dir":str(out)}),flush=True)

    return int(failed)


def capture_runtime(stages=None, assets=None, append=False):
    """Bounded audit world: live renderer LOD, real indoor physics and UI states."""
    import visual_test
    import datetime as dt
    from PIL import Image, ImageDraw
    directory = OUT / 'runtime'
    directory.mkdir(exist_ok=True)
    token = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    fixture = directory / f'fixture-{token}.json'
    data = json.loads((OUT / 'inventory.json').read_text())
    previous = json.loads((OUT / 'runtime-manifest.json').read_text()) if (stages or append) and (OUT / 'runtime-manifest.json').exists() else None
    if stages: data['runtime_stages'] = stages
    if assets: data['runtime_assets'] = assets
    data['runtime_result_file'] = f'results-{token}.json'
    registered = set(re.findall(r'^\s*"(\w+)": preload\("res://assets/vehicles/', (REPO/'godot/buildings_3d.gd').read_text(), re.M))
    data['lod_expected'] = []
    for row in data['assets']:
        if stages and 'legacy' in stages and row['mode']=='vehicle' and row['name']==row['kind'] and row['kind'] in ['saloon','hatchback','estate','suv','pickup','sports','city_car','panel_van']:
            data['lod_expected'].append(dict(asset=row['id'],system='legacy procedural car 35 m selector'))
        if assets and row['id'] not in assets: continue
        if not stages or 'lod' in stages:
            if row['mode']=='vehicle' and row['name']==row['kind'] and row['kind'] in registered:
                data['lod_expected'].append(dict(asset=row['id'],system='generated imported mesh LOD'))
            elif row['mode'] in ['person','animal']:
                data['lod_expected'].append(dict(asset=row['id'],system='live 40 m detail selector'))
    fixture.write_text(json.dumps(data, indent=2))
    godot = visual_test._godot()
    with (directory / f'capture-{token}.log').open('w') as log:
        result = subprocess.run([str(godot), '--path', visual_test._host_path(REPO / 'godot', godot),
                                 '--script', 'res://tools/visual_quality_audit_ui.gd' if stages==['ui_branches'] else 'res://tools/visual_quality_audit_runtime.gd', '--',
                                 visual_test._host_path(fixture, godot), visual_test._host_path(directory, godot)],
                                cwd=REPO, stdout=log, stderr=subprocess.STDOUT, timeout=660)
    manifest = json.loads((directory / data['runtime_result_file']).read_text())
    manifest.update(source_revision=visual_test._commit(), capture_returncode=result.returncode)
    for capture in manifest['captures']:
        raw = directory / capture['file']
        with Image.open(raw) as image:
            labelled = Image.new('RGB', (image.width, image.height + 30), '#16212c')
            labelled.paste(image, (0, 30))
            ImageDraw.Draw(labelled).text((8, 8), f"{capture['asset']} | {capture['angle']}", fill='white')
        labelled.save(raw, optimize=True)
        capture['file'] = 'runtime/' + capture['file']
        capture['resolution'] = list(labelled.size)
    if previous:
        families = {'lod': 'runtime-lod', 'legacy': 'runtime-lod', 'effects': 'runtime-effects', 'rooms': 'runtime-rooms', 'ui': 'runtime-ui','ui_branches':'runtime-ui-branches'}
        replaced = {families[stage] for stage in stages}
        fresh = {capture['file'] for capture in manifest['captures']}
        manifest['captures'] = [capture for capture in previous['captures']
                                if capture['file'] not in fresh and (append or capture['family'] not in replaced or assets and capture['asset'] not in assets)] + manifest['captures']
        if 'rooms' not in stages: manifest['homes'] = previous.get('homes', [])
        elif assets: manifest['homes'] = [home for home in previous.get('homes', []) if home['asset'] not in assets] + manifest['homes']
        sampled = {(row['asset'],row['system']) for row in manifest.get('lod',[])}
        manifest['lod'] = [row for row in previous.get('lod',[]) if (row['asset'],row['system']) not in sampled] + manifest.get('lod',[])
        requested = {(row['asset'],row['system']) for row in manifest.get('lod_expected',[])}
        manifest['lod_expected'] = [row for row in previous.get('lod_expected',[]) if (row['asset'],row['system']) not in requested] + manifest.get('lod_expected',[])
        manifest['prior_recovery'] = previous.get('recovery',previous.get('prior_recovery',''))
    (OUT / 'runtime-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    errors = validate_runtime(manifest, OUT)
    print(json.dumps({'captures': len(manifest['captures']), 'homes': len(manifest.get('homes', [])), 'errors': errors}, indent=2))
    return int(bool(errors) or result.returncode != 0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture",action="store_true")
    parser.add_argument("--check",action="store_true")
    parser.add_argument("--context",action="store_true")
    parser.add_argument("--distance",action="store_true")
    parser.add_argument("--runtime",action="store_true")
    parser.add_argument("--runtime-stages",nargs='+',choices=['lod','legacy','effects','rooms','ui','ui_branches'])
    parser.add_argument("--runtime-assets",nargs='+')
    parser.add_argument("--runtime-append",action='store_true')
    parser.add_argument("--gameplay",nargs="+")
    parser.add_argument("--compose",type=Path)
    args=parser.parse_args()
    OUT.mkdir(exist_ok=True)
    path=OUT/"inventory.json"
    gameplay_code=capture_gameplay(args.gameplay) if args.gameplay else 0
    if args.runtime: return capture_runtime(args.runtime_stages,args.runtime_assets,args.runtime_append)
    if args.capture:
        data=capture(inventory())
        data["summary"]=summary(data)
        path.write_text(json.dumps(data,indent=2)+"\n")
    if args.compose:
        data=json.loads((args.compose/"fixture.json").read_text())
        compose(data,args.compose)
        if (args.compose/"canvas-results.json").exists(): compose_canvas(data,args.compose)
        data["summary"]=summary(data)
        path.write_text(json.dumps(data,indent=2)+"\n")
    if args.context:
        data=capture_context(correct_inventory(json.loads(path.read_text())))
        data["summary"]=summary(data)
        path.write_text(json.dumps(data,indent=2)+"\n")
    if args.distance:
        data=capture_distance(json.loads(path.read_text()))
        data["summary"]=summary(data)
        path.write_text(json.dumps(data,indent=2)+"\n")
    if args.check:
        data=json.loads(path.read_text())
        errors=validate(data,OUT)
        if (OUT/'runtime-manifest.json').exists(): errors += validate_runtime(json.loads((OUT/'runtime-manifest.json').read_text()),OUT)
        if (OUT/'gap-matrix.json').exists(): errors += validate_gap_matrix(json.loads((OUT/'gap-matrix.json').read_text()),OUT)
        print("\n".join(errors) if errors else json.dumps(summary(data),indent=2))
        return int(bool(errors))
    return gameplay_code

if __name__=="__main__":
    raise SystemExit(main())
