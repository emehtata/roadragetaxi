import math
from datetime import date

import pytest

from theroadragetrip.electronic_sign_direction import approach, bind_sign, distance_on_approach, reference_direction
from theroadragetrip.electronic_signs import nearby_signs
from theroadragetrip.osm import Way
from theroadragetrip.physics import Car, SpatialWayGrid, update_car_physics


def road(points, **kwargs):
    return Way(points, 'primary', 4, ref='4', **kwargs)


def sign_at(x,y,bearing=0,**kwargs):
    sign = {'id':'test','type':'SPEEDLIMIT','road':'4','x':x,'y':y,'_effect_time':0,
            'speed_limit_kmh':80,'code':'','text':[],
            '_direction_line':((x-math.cos(bearing)*10,y-math.sin(bearing)*10),
                               (x+math.cos(bearing)*10,y+math.sin(bearing)*10))}
    return dict(sign,**kwargs)


def result(signs,car,current,ways):
    from datetime import datetime,timezone
    grid = SpatialWayGrid(ways)
    for sign in signs:
        sign['_binding'] = bind_sign(sign,grid)
    return nearby_signs(signs,car,current,datetime(2026,10,28,tzinfo=timezone.utc),grid)


@pytest.mark.parametrize('angle',[0,math.pi/2,-1.7])
@pytest.mark.parametrize('reverse_osm',[False,True])
def test_only_signs_facing_the_taxi_on_its_approach_are_shown(angle,reverse_osm):
    def p(x,y=0):return (x*math.cos(angle)-y*math.sin(angle),x*math.sin(angle)+y*math.cos(angle))
    points=[p(0),p(300)]
    way=road(points[::-1] if reverse_osm else points)
    car=Car(*p(20),angle,0)
    ahead=sign_at(*p(100),angle,id='ahead')
    opposite=sign_at(*p(80),angle+math.pi,id='opposite')
    behind=sign_at(*p(10),angle,id='behind')
    rows=result([opposite,behind,ahead],car,way,[way])
    assert [row['id'] for row in rows] == ['ahead']
    assert rows[0]['distance_m'] == 80
    car.heading += math.pi
    assert [row['id'] for row in result([ahead],car,way,[way])] == []


def test_parallel_carriageway_and_same_numbered_disconnected_road_are_excluded():
    east=road([(0,0),(300,0)],oneway=1)
    west=road([(300,20),(0,20)],oneway=1)
    disconnected=road([(350,0),(600,0)])
    car=Car(10,0,0,0)
    good=sign_at(100,0,id='good')
    wrong=sign_at(100,20,math.pi,id='wrong')
    far=sign_at(400,0,id='disconnected')
    assert [s['id'] for s in result([good,wrong,far],car,east,[east,west,disconnected])] == ['good']


def test_curved_connected_ways_use_path_distance_and_local_sign_direction():
    first=road([(0,0),(100,0)])
    second=road([(100,100),(100,0)])  # OSM order reverses at the join
    third=road([(100,100),(0,100)])
    car=Car(10,0,0,0)
    # Sign faces west, while the taxi currently faces east: the connected road bends around.
    sign=sign_at(50,100,math.pi)
    rows=result([sign],car,first,[first,second,third])
    assert len(rows)==1 and rows[0]['distance_m']==240


def test_fork_and_other_levels_fail_closed():
    first=road([(0,0),(100,0)])
    left=road([(100,0),(200,60)])
    right=road([(100,0),(200,-60)])
    car=Car(10,0,0,0)
    sign=sign_at(150,30,math.atan2(60,100))
    assert result([sign],car,first,[first,left,right]) == []
    bridge=road([(0,0),(300,0)],layer=1)
    assert bind_sign(sign_at(100,0),SpatialWayGrid([bridge])) is None
    assert approach(car,bridge,SpatialWayGrid([bridge]),700)==[]


def test_reversing_and_passing_update_the_shown_sign_in_the_physics_loop():
    way=road([(-300,0),(300,0)])
    grid=SpatialWayGrid([way])
    sign=sign_at(3,0)
    binding=bind_sign(sign,grid)
    car=Car(0,0,0,0,engine_on=True)
    assert distance_on_approach(binding,approach(car,way,grid,700))==pytest.approx(3)
    for _ in range(90):
        update_car_physics(car,1,0,0,0,1/30,ways=[way],spatial_grid=grid)
    assert car.x > 3
    assert distance_on_approach(binding,approach(car,way,grid,700)) is None
    car.x,car.speed=0,-0.05
    assert distance_on_approach(binding,approach(car,way,grid,700)) is None


def test_unknown_direction_and_ambiguous_matching_are_hidden():
    way=road([(0,0),(300,0)])
    unknown=sign_at(100,0,_direction_line=None)
    assert result([unknown],Car(0,0,0,0),way,[way])==[]
    parallel=road([(0,0.1),(300,0.1)])
    assert bind_sign(sign_at(100,0.05),SpatialWayGrid([way,parallel])) is None


def test_authoritative_reference_direction_is_independent_of_osm_point_order():
    calls=[]
    class Client:
        def get_json(self,path,params):
            calls.append((path,params))
            return {'features':[{'properties':{'tie':4,'osa':12,'osa_loppu':12,'ajorata':2,
                    'etaisyys':90,'etaisyys_loppu':110,'x':10,'y':20,'x_loppu':30,'y_loppu':20}}]}
    sign={'road_address':(4,12,100),'carriageway':'LEFT','direction':'DECREASING'}
    assert reference_direction(Client(),sign,date(2026,10,28)) == ((30,20),(10,20))
    assert calls[0][1]['ajorata']==2 and calls[0][1]['tilannepvm']=='28.10.2026'
    sign['direction']='INCREASING'
    assert reference_direction(Client(),sign,date(2026,10,28)) == ((10,20),(30,20))
    sign['direction']=''
    assert reference_direction(Client(),sign,date(2026,10,28)) is None


@pytest.mark.parametrize('body',[None,{}, {'features':None},{'features':[None,{'properties':'bad'}]}])
def test_bad_direction_responses_do_not_leak_unbound_signs(body):
    class Client:
        def get_json(self,*args,**kwargs):return body
    sign={'road_address':(4,12,100),'carriageway':'LEFT','direction':'INCREASING'}
    assert reference_direction(Client(),sign,date(2026,10,28)) is None


def test_map_streaming_rematches_direction_binding_after_new_roads_load():
    from datetime import datetime,timezone
    from theroadragetrip.digitraffic_road import LiveRoadworks
    from types import SimpleNamespace
    now=[0.0]
    source=sign_at(150,0,lon=150,lat=0)
    service=SimpleNamespace(roadworks=[],variable_signs=[source],revision=1,request=lambda *a:None)
    live=LiveRoadworks(service,lambda x,y:(x,y),clock=lambda:now[0])
    first=road([(0,0),(100,0)])
    second=road([(100,0),(300,0)])
    grid=SpatialWayGrid([first])
    moment=datetime(2026,10,28,tzinfo=timezone.utc)
    live.update(0,0,moment,moment,1,grid)
    assert live.electronic_signs_near(Car(0,0,0,0),first)==[]
    grid.rebuild([first,second]);now[0]=6
    live.update(0,0,moment,moment,2,grid)
    assert live.electronic_signs_near(Car(0,0,0,0),first)[0]['distance_m']==150


def test_roadworks_publish_before_slow_direction_metadata_finishes(monkeypatch):
    import threading
    from datetime import datetime,timezone
    from theroadragetrip import electronic_signs as es
    from theroadragetrip.digitraffic_road import DigitrafficClient,RoadDataService
    entered,release=threading.Event(),threading.Event()
    def fetch(*args):
        entered.set();release.wait(3)
        return [],True
    monkeypatch.setattr(es,'fetch_signs',fetch)
    service=RoadDataService(DigitrafficClient(None,lambda *a:b'{"features":[]}'),lambda x,y:(25.4,65.0))
    try:
        service.request(0,0,datetime(2026,10,28,tzinfo=timezone.utc))
        assert entered.wait(1)
        assert service.revision >= 1
    finally:
        release.set();service.close()
