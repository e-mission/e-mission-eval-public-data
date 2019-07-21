import argparse
import logging
import json
import copy
import arrow
import requests
import osmapi
import re
import polyline as pl

import osrm as osrm

sensing_configs = json.load(open("sensing_regimes.all.specs.json"))

def validate_and_fill_datetime(current_spec):
    ret_spec = copy.copy(current_spec)
    timezone = current_spec["region"]["timezone"]
    ret_spec["start_ts"] = arrow.get(current_spec["start_fmt_date"], tzinfo=timezone).timestamp
    ret_spec["end_ts"] = arrow.get(current_spec["end_fmt_date"], tzinfo=timezone).timestamp
    return ret_spec

def node_to_geojson_coords(node_id):
    osm = osmapi.OsmApi()
    node_details = osm.NodeGet(node_id)
    return [node_details["lon"], node_details["lat"]]

def get_route_coords(mode, waypoint_coords):
    if mode == "CAR" \
      or mode == "WALKING" \
      or mode == "BICYCLING" \
      or mode == "BUS":
        # Use OSRM
        overview_geometry_params = {"overview": "full",
            "geometries": "polyline", "steps": "false"}
        route_coords = osrm.get_route_points(mode, waypoint_coords, overview_geometry_params)
        return route_coords
    else:
        raise NotImplementedError("OSRM does not support train modes at this time")

def _fill_coords_from_id(loc):
    if loc is None:
        return None
    loc["coordinates"] = node_to_geojson_coords(loc["osm_id"])
    return loc["coordinates"]

def validate_and_fill_calibration_tests(curr_spec):
    modified_spec = copy.copy(curr_spec)
    calibration_tests = modified_spec["calibration_tests"]
    for t in calibration_tests:
        _fill_coords_from_id(t["start_loc"])
        _fill_coords_from_id(t["end_loc"])
        t["config"] = sensing_configs[t["config"]["id"]]
    return modified_spec

def coords_swap(lon_lat):
    return list(reversed(lon_lat))

def get_route_from_osrm(t, start_coords, end_coords):
    if "route_waypoints" in t:
        waypoints = t["route_waypoints"]
        waypoint_coords = [node_to_geojson_coords(node_id) for node_id in waypoints]
        t["waypoint_coords"] = waypoint_coords
    elif "waypoint_coords" in t:
        waypoint_coords = t["waypoint_coords"]
    logging.debug("waypoint_coords = %s..." % waypoint_coords[0:3])
    route_coords = get_route_coords(t["mode"],
        [start_coords] + waypoint_coords + [end_coords])
    return route_coords

def get_route_from_polyline(t):
    return pl.PolylineCodec().decode(t["polyline"])

# Porting the perl script at
# https://wiki.openstreetmap.org/wiki/Relations/Relations_to_GPX to python

def get_way_list(relation_details):
    wl = []
    for member in relation_details["member"]:
        # print(member["ref"], member["type"])
        assert member["type"] != "relation", "This is a parent relation for child %d, expecting only child relations" % member["ref"]
        if member["type"] == "way" and member["role"] != "platform":
            wl.append(member["ref"])
    return wl

# way details is an array of n-1 node entries followed by a way entry
# the way entry has an "nd" field which is an array of node ids in the correct
# order the n-1 node entries are not necessarily in the correct order but
# provide the id -> lat,lng mapping
# Note also that the way can sometimes have the nodes in the reversed order
# e.g. way 367132251 in relation 9605483 is reversed compared to ways 
# 368345083 and 27422567 before it
# this function automatically detects that and reverses the node array
def get_coords_for_way(wid, prev_last_node=-1):
    osm = osmapi.OsmApi()
    lat = {}
    lon = {}
    coords_list = []
    way_details = osm.WayFull(wid)
    # print("Processing way %d with %d nodes" % (wid, len(way_details) - 1))
    for e in way_details:
        if e["type"] == "node":
            lat[e["data"]["id"]] = e["data"]["lat"]
            lon[e["data"]["id"]] = e["data"]["lon"]
        if e["type"] == "way":
            assert e["data"]["id"] == wid, "Way id mismatch! %d != %d" % (e["data"]["id"], wl[0])
            ordered_node_array = e["data"]["nd"]
            if prev_last_node != -1 and ordered_node_array[-1] == prev_last_node:
                print("LAST entry %d matches prev_last_node %d, REVERSING order for %d" %
                      (ordered_node_array[-1], prev_last_node, wid))
                ordered_node_array = list(reversed(ordered_node_array))
            for on in ordered_node_array:
                # Returning lat,lon instead of lon,lat to be consistent with
                # the returned values from OSRM. Since we manually swap the
                # values later
                coords_list.append([lat[on], lon[on]])
    return ordered_node_array, coords_list

def get_coords_for_relation(rid, start_node, end_node):
    osm = osmapi.OsmApi()
    relation_details = osm.RelationGet(rid)
    wl = get_way_list(relation_details)
    print("Relation %d mapped to %d ways" % (rid, len(wl)))
    coords_list = []
    on_list = []
    prev_last_node = -1
    for wid in wl:
        w_on_list, w_coords_list = get_coords_for_way(wid, prev_last_node)
        on_list.extend(w_on_list)
        coords_list.extend(w_coords_list)
        prev_last_node = w_on_list[-1]
        print("After adding %d entries from wid %d, curr count = %d" % (len(w_on_list), wid, len(coords_list)))
    start_index = on_list.index(start_node)
    end_index = on_list.index(end_node)
    assert start_index <= end_index, "Start index %d is before end %d" % (start_index, end_index)
    return coords_list[start_index:end_index+1]

def get_route_from_relation(t):
    return get_coords_for_relation(t["relation"],
        t["start_loc"]["osm_id"], t["end_loc"]["osm_id"])

def validate_and_fill_leg(t):
    start_coords = _fill_coords_from_id(t["start_loc"])
    end_coords = _fill_coords_from_id(t["end_loc"])
    # there are three possible ways in which users can specify routes
    # - waypoints from OSM, which we will map into coordinates and then
    # move to step 2
    # - list of coordinates, which we will use to find route coordinates
    # using OSRM
    # - a relation with start and end nodes, used only for public transit trips
    # - a polyline, which we can get from external API calls such as OTP or Google Maps
    # Right now, we leave the integrations unspecified because there is not
    # much standardization other than with google maps
    # For example, the VTA trip planner () clearly uses OTP
    # () but the path (api/otp/plan?) is different from the one for our OTP
    # integration (otp/routers/default/plan?)
    # But once people figure out the underlying call, they can copy-paste the
    # geometry into the spec.
    if "route_waypoints" in t or "waypoint_coords" in t:
        route_coords = get_route_from_osrm(t, start_coords, end_coords)
    elif "polyline" in t:
        route_coords = get_route_from_polyline(t)
    elif "relation" in t:
        route_coords = get_route_from_relation(t)

    t["route_coords"] = [coords_swap(rc) for rc in route_coords]

def validate_and_fill_eval_trips(curr_spec):
    modified_spec = copy.copy(curr_spec)
    eval_trips = modified_spec["evaluation_trips"]
    for t in eval_trips:
        if "legs" in t:
            for l in t["legs"]:
                validate_and_fill_leg(l)
        else:
            # unimodal trip
            validate_and_fill_leg(t)
    return modified_spec

def validate_and_fill_sensing_settings(curr_spec):
    modified_spec = copy.copy(curr_spec)
    for ss in modified_spec["sensing_settings"]:
        compare_list = ss["compare"]
        ss["name"] = " v/s ".join(compare_list)
        ss["sensing_configs"] = [sensing_configs[cr] for cr in compare_list]
    return modified_spec

if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    parser = argparse.ArgumentParser(prog="autofill_eval_spec")

    parser.add_argument("in_spec_file", help="file to autofill")
    parser.add_argument("out_spec_file", help="autofilled version of in_spec_file")

    args = parser.parse_args()

    print("Reading input from %s" % args.in_spec_file) 
    current_spec = json.load(open(args.in_spec_file))

    dt_spec = validate_and_fill_datetime(current_spec)
    calib_spec = validate_and_fill_calibration_tests(dt_spec)
    eval_spec = validate_and_fill_eval_trips(calib_spec)
    settings_spec = validate_and_fill_sensing_settings(eval_spec)
   
    print("Writing output to %s" % args.out_spec_file) 
    json.dump(settings_spec, open(args.out_spec_file, "w"), indent=2)
