"""Diagnostic probes of the unfixed baseline, not passing-compliance tests.
Invert the relevant expectations when implementing each planned fix.
"""
import json
from types import SimpleNamespace as NS
from theroadragetrip.pedestrian import PedestrianManager, PedestrianNetwork
from theroadragetrip.npc import NPCState, NPCVehicleManager, place_parked_npc
from theroadragetrip.osm import Way, StopSign
from theroadragetrip.physics import Car
from theroadragetrip.residents import ResidentManager
from theroadragetrip.traffic_rules import crossing_yield_decision, decide_traffic_action

results = {}
manager = PedestrianManager([], target_count=0)
group = NS(member_resident_ids=[101], boarded_resident_ids={101}, destination_entrance=None)
vehicle = NS(state=NPCState.PARKED, trip_group=group, x=0, y=0, heading=0, width_m=1.8)
manager.traffic_vehicles = [vehicle]
manager.entrance_locations = [(10, 0)]
manager.spawn_pedestrian_at = lambda *args: NS(resident_id=None)
manager._materialize_parked_drivers()
assert len(manager.pedestrians) == 1 and not group.boarded_resident_ids
ped = manager.pedestrians[0]
ped.state = 'entering_vehicle'
ped.vehicle_entry_timer = 0
manager._update_linked_driver(ped, 1/30)
assert group.boarded_resident_ids == {101} and ped.state == 'despawning'
manager.pedestrians.clear()
manager._materialize_parked_drivers()
assert len(manager.pedestrians) == 1 and not group.boarded_resident_ids
results['reboarded_member_rematerialized_next_frame'] = True

car = Car(-10, 0, 0, 0)
car.way = Way([(-100,0),(100,0)], 'residential', 3.5)
stop = StopSign(-5,0,direction_angle=0)
assert crossing_yield_decision(car, [], signs=[stop]) is None
results['stop_sign_without_other_vehicle_has_no_stop_decision'] = True

red = NS(x=0,y=0,get_state=lambda t:'yellow',direction_angle=0)
decision = decide_traffic_action(-10,0,0,[red],0,speed_limit_mps=13.9)
assert decision.action == 'PROCEED'
results['yellow_at_zero_actual_speed_uses_cruise_speed_instead'] = decision.reason

manager._crossing_grid = {(0,0):[NS(x=0,y=0,crossing_type='traffic_signals')]}
manager.logical_intersections = [NS(center=(0,0),radius_m=20, approaches=[NS(signal_group=NS(get_state=lambda t:'green'))])]
assert manager._is_pedestrian_red_light(NS(x=0,y=0,state='crossing'))
results['already_crossing_pedestrian_stopped_by_any_nearby_green_group'] = True

network = PedestrianNetwork([Way([(0,0),(10,0)],'footway',1),Way([(100,0),(110,0)],'footway',1)])
route = network.route((0,0),(110,0))
assert route == [(0,0),(110,0)]
results['disconnected_pedestrian_network_falls_back_to_direct_connector'] = route

npcs = NPCVehicleManager(target_count=0,min_count=0)
a = place_parked_npc(1,(0,0),None)
b = place_parked_npc(2,(0,0),None)
a.way = Way([(-10,0),(10,0)],'residential',3.5,layer=0)
b.way = Way([(-10,0),(10,0)],'residential',3.5,layer=1)
a.car.layer = 0
b.car.layer = 1
assert a.layer == 0 and b.layer == 1
npcs.vehicles = [a,b]
hit = npcs._check_vehicle_collision(a,[b],ResidentManager(),None,0)
assert hit and a.state == NPCState.CRASHED and b.state == NPCState.CRASHED
results['different_layer_overlap_still_triggers_vehicle_collision'] = True
print(json.dumps(results,indent=2))
