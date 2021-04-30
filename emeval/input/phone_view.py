# Fill in the phone view of the calibration data
# More details in __init__.py
# Resulting data structure
# - android
#   - ucb-sdb-android-1
#       - transitions
#       - calibration_transitions
#       - calibration_ranges
#           - high_accuracy_stationary_0
#               - battery_df
#               - location_df
#               - ....
#           - high_accuracy_stationary_1
#               - battery_df
#               - location_df
#           - ....
#           - high_accuracy_train_AO
#               - ....
#           - medium_accuracy_train_AO
#               - battery_df
#               - location_df
#   - ucb-sdb.android-2
#   -...
# - ios
#   - ucb-sdb-ios-1
#   - ucb-sdb-ios-2
#   - ...
#


import copy
import arrow
import pandas as pd
import emeval.validate.phone_view as evpv


TIME_SYNC_FUZZ = 0 # seconds = 1 minute

# keys
EVAL_TRANSITION = "manual/evaluation_transition"
BG_BATTERY = "background/battery"
BG_LOCATION = "background/location"
BG_FILTERED_LOCATION = "background/filtered_location"
BG_MOTION_ACTIVITY = "background/motion_activity"
SM_TRANSITION = "statemachine/transition"

class PhoneView:
    def __init__(self, spec_details):
        self.phone_view_map = {}
        self.spec_details = spec_details

        print(20 * "-", "About to read transitions from server", 20 * "-")
        self.fill_transitions()
        print(20 * "-", "About to fill calibration ranges", 20 * "-")
        self.fill_calibration_ranges()
        print(20 * "-", "About to fill evaluation ranges", 20 * "-")
        self.fill_evaluation_ranges()
        print(20 * "-", "About to fill evaluation trips", 20 * "-")
        self.fill_eval_role_maps()
        self.fill_accuracy_control_trip_ranges()
        print(20 * "-", "About to fill in evaluation sections", 20 * "-")
        self.fill_accuracy_control_section_ranges()
        print(20 * "-", "About to copy trip and section ranges", 20 * "-")
        self.copy_trip_ranges_to_other_accuracy_control()
        self.copy_trip_ranges_to_eval_power_maps()
        print(20 * "-", "About to fill in battery information", 20 * "-")
        self.fill_battery_df("calibration")
        self.fill_battery_df("evaluation")
        print(20 * "-", "About to fill in location information", 20 * "-")
        self.fill_location_df("calibration")
        self.fill_location_df("evaluation")
        print(20 * "-", "About to fill in motion activity information", 20 * "-")
        self.fill_motion_activity_df("calibration")
        self.fill_motion_activity_df("evaluation")
        print(20 * "-", "About to fill in transition information", 20 * "-")
        self.fill_transition_df("calibration")
        self.fill_transition_df("evaluation")
        print(20 * "-", "About to select trip specific ranges", 20 * "-")
        self.fill_trip_specific_battery_and_locations()
        print(20 * "-", "Done populating information from server", 20 * "-")

    def validate(self):
        print(20 * "-", "About to validate calibration settings", 20 * "-")
        evpv.validate_calibration_settings(self)
        print(20 * "-", "About to validate evaluation settings", 20 * "-")
        evpv.validate_evaluation_settings(self)
        print(20 * "-", "About to validate calibration range durations", 20 * "-")
        evpv.validate_range_durations_for_calibration(self)
        print(20 * "-", "About to validate evaluation range durations", 20 * "-")
        evpv.validate_range_durations_for_evaluation(self)

    def map(self):
        return self.phone_view_map

    #
    # BEGIN: Imported from Validate_calibration_*.ipynb
    #
    def fill_transitions(self):
        self.phone_view_map = copy.deepcopy(self.spec_details.phone_labels)
        for phoneOS, phone_map in self.phone_view_map.items():
            print("Reading data for %s phones" % phoneOS)
            for phone_label in phone_map:
                print("Loading transitions for phone %s" % phone_label)
                curr_phone_transitions = self.spec_details.retrieve_data(
                    phone_label, [EVAL_TRANSITION],
                    self.spec_details.eval_start_ts, self.spec_details.eval_end_ts)
                curr_phone_role = phone_map[phone_label]
                phone_map[phone_label] = {"role": curr_phone_role}
                phone_map[phone_label][EVAL_TRANSITION] = curr_phone_transitions

    """
    Inputs:
    - phone_view: the phone view with retrieved transitions
    - start_tt, end_tt: string representation of the start and end transitions
        (retrieved in case the pipeline had not yet run)
    - start_ti, end_ti: int representation of the start and end transitions
        (retrieved in case the pipeline has run)
    - storage_key: the prefix for the storage (e.g. calibration -> calibration_transitions)
    """
    def filter_transitions(self, start_tt, end_tt, start_ti, end_ti,
        storage_key_prefix):
        for phoneOS, phone_map in self.phone_view_map.items():
            print("Processing data for %s phones" % phoneOS)
            for phone_label in phone_map:
                print("Processing transitions for phone %s" % phone_label)
                curr_phone_transitions = [t["data"] for t in phone_map[phone_label][EVAL_TRANSITION]]
                # print(curr_phone_transitions)
                curr_calibration_transitions = [t for t in curr_phone_transitions
                    if (t["transition"] in [start_tt, end_tt, start_ti, end_ti]) and
                    t["spec_id"] == self.spec_details.CURR_SPEC_ID]
                print("Filtered %d total -> %d calibration transitions " %
                    (len(curr_phone_transitions), len(curr_calibration_transitions)))
                phone_map[phone_label]["{}_transitions".format(storage_key_prefix)] = \
                    sorted(curr_calibration_transitions, key=lambda t: t["ts"])


    """
    Convert list of transitions into a list of ranges.
    Inputs are the same as `filter_transitions`: 
    """
    @staticmethod
    # We expect that transitions occur in pairs
    def transitions_to_ranges(transition_list, start_tt, end_tt, start_ti, end_ti,
            spec_end_ts):
        # re-sort transitions into proper order -- START and STOP transitions must alternate
        for i in range(0, len(transition_list)-2, 2):
            if "START" in transition_list[i]["transition"] and "START" in transition_list[i+1]["transition"] and "STOP" in transition_list[i+2]["transition"]:
                transition_list[i+1], transition_list[i+2] = transition_list[i+2], transition_list[i+1]

        start_transitions = transition_list[::2]
        end_transitions = transition_list[1::2]

        print("\n".join([str((t["transition"], t["trip_id"], t["ts"], t["write_ts"])) for t in transition_list]))

        if len(transition_list) % 2 == 0:
            print("All ranges are complete, nothing to change")
        else:
            print("Incomplete range, adding fake end transition")
            last_start_transition = start_transitions[-1]
            fake_end_transition = copy.deepcopy(last_start_transition)
            fake_end_transition["transition"] = end_tt
            print(last_start_transition, fake_end_transition)
            curr_ts = arrow.get().timestamp
            if curr_ts > spec_end_ts:
                fake_end_transition["ts"] = spec_end_ts
            else:
                fake_end_transition["ts"] = curr_ts
            fake_end_transition["write_ts"] = fake_end_transition["ts"]

            if "fmt_time" in last_start_transition:
                fake_end_transition["fmt_time"] = arrow.get(curr_ts).to(eval_tz)
            if "local_dt" in fake_end_transition:
                del fake_end_transition["local_dt"]
            end_transitions.append(fake_end_transition)

        # print("\n".join([str((t["transition"], t["trip_id"], t["ts"])) for t in start_transitions]))
        # print("\n".join([str((t["transition"], t["trip_id"], t["ts"])) for t in end_transitions]))
        unique_trip_ids = set([t["trip_id"] for t in transition_list])
        print(unique_trip_ids)

        range_list = []
        range_count_map = dict.fromkeys(unique_trip_ids, 0)
        for (s, e) in zip(start_transitions, end_transitions):
            # print("------------------------------------- \n %s -> \n %s" % (s, e))
            assert s["transition"] == start_tt or s["transition"] == start_ti, "Start transition has %s transition" % s["transition"]
            assert e["transition"] == end_tt or e["transition"] == end_ti, "Stop transition has %s transition" % s["transition"]
            assert s["trip_id"] == e["trip_id"], "trip_id mismatch! %s != %s" % (s["trip_id"], e["trip_id"])
            assert e["ts"] > s["ts"], "end %s is before start %s" % (arrow.get(e["ts"]), arrow.get(s["ts"]))
            for f in ["spec_id", "device_manufacturer", "device_model", "device_version"]:
                assert s[f] == e[f], "Field %s mismatch! %s != %s" % (f, s[f], e[f])

            # Handle multiple ranges. for one range, we will have two
            # transitions: start and stop
            curr_trip_id = s["trip_id"] + "_"+ str(range_count_map[s["trip_id"]])
            curr_range = {"trip_id": curr_trip_id,
                "trip_id_base" : s["trip_id"],
                "trip_run": range_count_map[s["trip_id"]],
                "start_ts": s["write_ts"], "end_ts": e["write_ts"],
                "duration": (e["write_ts"] - s["write_ts"])}
            range_count_map[s["trip_id"]] = range_count_map[s["trip_id"]] + 1
            range_list.append(curr_range)
            
        return range_list

    def fill_calibration_ranges(self):
        self.filter_transitions(
            "START_CALIBRATION_PERIOD", "STOP_CALIBRATION_PERIOD", 0, 1,
            "calibration")
        # ios_1_transitions = self.phone_view_map["ios"]["ucb-sdb-ios-1"]["calibration_transitions"]
        # print("\n".join([str((t["transition"], t["trip_id"], t["ts"], arrow.get(t["ts"]).to(self.spec_details.eval_tz))) for t in ios_1_transitions]))
        for phoneOS, phone_map in self.phone_view_map.items():
            print("Processing data for %s phones" % phoneOS)
            for phone_label in phone_map:
                print("-" * 10, phone_label)
                curr_calibration_ranges = PhoneView.transitions_to_ranges(
                    phone_map[phone_label]["calibration_transitions"],
                    "START_CALIBRATION_PERIOD", "STOP_CALIBRATION_PERIOD", 0, 1,
                    self.spec_details.eval_end_ts)
                print("Found %d ranges of duration %s for phone %s" %
                    (len(curr_calibration_ranges),
                    [r["duration"] for r in curr_calibration_ranges],
                    phone_label))
                phone_map[phone_label]["calibration_ranges"] = curr_calibration_ranges

    ## Link evaluation ranges to each other
    # Since the evaluation ranges have separate IDs, it is hard to link them
    # the way we link the calibration ranges.  So let's add a common field
    # (`eval_common_trip_id`) to each of the matching
    # ranges for easy checking

    def link_common_eval_ranges(self):
        for phoneOS, phone_map in self.phone_view_map.items(): # android, ios
            print("Processing data for %s phones" % phoneOS)
            all_eval_ranges = [m["evaluation_ranges"] for m in phone_map.values()]
            # print(all_eval_ranges, [len(a) for a in all_eval_ranges], set([len(a) for a in all_eval_ranges]))
            # all the lengths are equal - i.e. the set of lengths has one entr
            assert len(set([len(a) for a in all_eval_ranges])) == 1
            for ctuple in zip(*all_eval_ranges):
                if len(ctuple) > 2:
                    eval_cols = ctuple[1:-1]
                else:
                    # if we only have two phones, maybe because we are repeating trips
                    eval_cols = ctuple
                # print([ct["trip_id"] for ct in ctuple], [ct["trip_id"] for ct in eval_cols])
                get_common_name = lambda r: r["trip_id"].split(":")[0]
                get_separate_role = lambda r: r["trip_id"].split(":")[1]
                common_names = set([get_common_name(r) for r in eval_cols])
                separate_roles = [get_separate_role(r) for r in eval_cols]
                curr_run_list = [sr.split("_")[1] for sr in separate_roles]
                assert len(set(curr_run_list)) == 1
                curr_run = list(set(curr_run_list))[0]
                # print(common_names, separate_roles)
                assert len(common_names) == 1
                common_name = list(common_names)[0]
                # print(common_name)
                for r in ctuple:
                    r["eval_common_trip_id"] = common_name
                ctuple[0]["eval_role"] = "accuracy_control_"+curr_run
                ctuple[0]["eval_role_base"] = "accuracy_control"
                ctuple[0]["eval_role_run"] = curr_run
                for r, sr in zip(eval_cols, separate_roles):
                    r["eval_role"] = sr
                    sr_split = sr.split("_")
                    r["eval_role_base"] = sr_split[0]
                    r["eval_role_run"] = sr_split[1]
                ctuple[-1]["eval_role"] = "power_control_"+curr_run
                ctuple[-1]["eval_role_base"] = "power_control"
                ctuple[-1]["eval_role_run"] = curr_run

    def fill_evaluation_ranges(self):
        self.filter_transitions(
            "START_EVALUATION_PERIOD", "STOP_EVALUATION_PERIOD", 2, 3,
            "evaluation")
        for phoneOS, phone_map in self.phone_view_map.items():
            print("Processing data for %s phones" % phoneOS)
            for phone_label in phone_map:
                curr_evaluation_ranges = PhoneView.transitions_to_ranges(
                    phone_map[phone_label]["evaluation_transitions"],
                    "START_EVALUATION_PERIOD", "STOP_EVALUATION_PERIOD", 2, 3,
                    self.spec_details.eval_end_ts)
                print("Found %d ranges for phone %s" % (len(curr_evaluation_ranges), phone_label))
                phone_map[phone_label]["evaluation_ranges"] = curr_evaluation_ranges
        self.link_common_eval_ranges()

    def fill_battery_df(self, storage_key):
        for phoneOS, phone_map in self.phone_view_map.items():
            print("Processing data for %s phones" % phoneOS)
            for phone_label in phone_map:
                curr_calibration_ranges = phone_map[phone_label]["{}_ranges".format(storage_key)]
                for r in curr_calibration_ranges:
                    battery_entries = self.spec_details.retrieve_data(phone_label, [BG_BATTERY], r["start_ts"], r["end_ts"])
                    # ios entries before running the pipeline are marked with battery_level_ratio, which is a float from 0 ->1
                    # convert it to % to be consistent with android and easier to understand
                    if phoneOS == "ios":
                        for e in battery_entries:
                            if "battery_level_pct" not in e["data"]:
                                e["data"]["battery_level_pct"] = e["data"]["battery_level_ratio"] * 100
                                del e["data"]["battery_level_ratio"]
                    r[BG_BATTERY] = battery_entries
                    battery_df = pd.DataFrame([e["data"] for e in battery_entries])
                    if len(battery_df) > 0:
                        battery_df["hr"] = (battery_df.ts-r["start_ts"])/3600.0
                    r["battery_df"] = battery_df

    def fill_location_df(self, storage_key):
        for phoneOS, phone_map in self.phone_view_map.items():
            print("Processing data for %s phones" % phoneOS)
            for phone_label in phone_map:
                curr_calibration_ranges = phone_map[phone_label]["{}_ranges".format(storage_key)]
                for r in curr_calibration_ranges:
                    r[BG_LOCATION] = self.spec_details.retrieve_data(phone_label,
                        [BG_LOCATION],
                        r["start_ts"], r["end_ts"])
                    r[BG_FILTERED_LOCATION] = self.spec_details.retrieve_data(
                        phone_label,
                        [BG_FILTERED_LOCATION],
                        r["start_ts"], r["end_ts"])
                    location_df = pd.DataFrame([e["data"] for e in
                        r[BG_LOCATION]])
                    filtered_location_df = pd.DataFrame([e["data"] for e in
                        r[BG_FILTERED_LOCATION]])
                    if len(location_df) > 0:
                        location_df["hr"] = (location_df.ts-r["start_ts"])/3600.0
                    if len(filtered_location_df) > 0:
                        filtered_location_df["hr"] = (filtered_location_df.ts-r["start_ts"])/3600.0
                    r["location_df"] = location_df
                    r["filtered_location_df"] = filtered_location_df

    def fill_motion_activity_df(self, storage_key):
        for phoneOS, phone_map in self.phone_view_map.items():
            print("Processing data for %s phones" % phoneOS)
            for phone_label in phone_map:
                curr_calibration_ranges = phone_map[phone_label]["{}_ranges".format(storage_key)]
                for r in curr_calibration_ranges:
                    r[BG_MOTION_ACTIVITY] = self.spec_details.retrieve_data(phone_label, [BG_MOTION_ACTIVITY], r["start_ts"], r["end_ts"])
                    motion_activity_df = pd.DataFrame([e["data"] for e in r[BG_MOTION_ACTIVITY]])
                    if "ts" not in motion_activity_df.columns:
                        print("motion activity has not been processed, copying write_ts -> ts")
                        motion_activity_df["ts"] = [e["metadata"]["write_ts"] for e in r[BG_MOTION_ACTIVITY]]
                        motion_activity_df["fmt_time"] = [arrow.get(e["metadata"]["write_ts"]).to(self.spec_details.eval_tz) for e in r[BG_MOTION_ACTIVITY]]
                    motion_activity_df["hr"] = (motion_activity_df.ts-r["start_ts"])/3600.0
                    r["motion_activity_df"] = motion_activity_df

    def fill_transition_df(self, storage_key):
        for phoneOS, phone_map in self.phone_view_map.items():
            print("Processing data for %s phones" % phoneOS)
            for phone_label in phone_map:
                curr_calibration_ranges = phone_map[phone_label]["{}_ranges".format(storage_key)]
                for r in curr_calibration_ranges:
                    transition_entries = self.spec_details.retrieve_data(
                        phone_label, [SM_TRANSITION], r["start_ts"], r["end_ts"])
                    # ios entries before running the pipeline are marked with battery_level_ratio, which is a float from 0 ->1
                    # convert it to % to be consistent with android and easier to understand
                    r[SM_TRANSITION] = transition_entries
                    transition_df = pd.DataFrame([e["data"] for e in transition_entries])
                    if "ts" in transition_df.columns:
                        if "fmt_time" not in transition_df.columns:
                            print("transition has not been processed, creating ts -> fmt_time")
                            transition_df["fmt_time"] = [arrow.get(e["data"]["ts"]).to(self.spec_details.eval_tz) for e in transition_entries]
                        transition_df["hr"] = (transition_df.ts-r["start_ts"])/3600.0
                    r["transition_df"] = transition_df


    def fill_eval_role_maps(self):
        self.accuracy_control_maps = {}
        self.power_control_maps = {}
        self.eval_phone_maps = {}

        for phoneOS, phone_map in self.phone_view_map.items():
            print("Processing data for %s phones" % phoneOS)
            self.eval_phone_maps[phoneOS] = {}
            for phone_label in phone_map:
                curr_role = phone_map[phone_label]["role"]
                if curr_role == "accuracy_control":
                    self.accuracy_control_maps[phoneOS] = phone_map[phone_label]
                elif curr_role == "power_control":
                    self.power_control_maps[phoneOS] = phone_map[phone_label]
                else:
                    assert curr_role.startswith("evaluation")
                    self.eval_phone_maps[phoneOS][phone_label] = phone_map[phone_label]

        print("Lengths (accuracy, power, eval) = (%d, %d, %d)" %
            (len(self.accuracy_control_maps),
            len(self.power_control_maps),
            len(self.eval_phone_maps)))
        print("keys (accuracy, power, eval) = (%s, %s, %s)" %
            (self.accuracy_control_maps.keys(),
            self.power_control_maps.keys(),
            self.eval_phone_maps.keys()))
        print("eval_phone_keys (android, ios) = (%s, %s)" %
            (self.eval_phone_maps["android"].keys(), self.eval_phone_maps["ios"].keys()))

    def fill_accuracy_control_trip_ranges(self):
        for phoneOS, phone_map in self.accuracy_control_maps.items():
            curr_control_transitions = [t["data"] for t in phone_map[EVAL_TRANSITION]] # from control phone
            curr_evaluation_ranges = phone_map["evaluation_ranges"] # from this phone
            trip_type_check = lambda t: t["transition"] in ["START_EVALUATION_TRIP", "STOP_EVALUATION_TRIP", 4, 5]
            trip_time_check = lambda t, r: t["ts"] >= r["start_ts"] and t["ts"] <= r["end_ts"]
            for i, r in enumerate(curr_evaluation_ranges):
                # We have to get the evaluation details from one of the evaluation phones
                curr_eval_trips_transitions = [t for t in curr_control_transitions if trip_type_check(t) and trip_time_check(t, r)]
                # print("\n".join([str((t["transition"], t["trip_id"], t["ts"], arrow.get(t["ts"]).to(eval_tz))) for t in curr_eval_trips_transitions]))
                # print(len(curr_eval_trips_transitions))
                curr_eval_trips_ranges = PhoneView.transitions_to_ranges(
                    curr_eval_trips_transitions,
                    "START_EVALUATION_TRIP", "STOP_EVALUATION_TRIP", 4, 5,
                    self.spec_details.eval_end_ts)
                print("%s: Found %s trips for evaluation %s" % (phoneOS, len(curr_eval_trips_ranges), r["trip_id"]))
                # print(curr_eval_trips_ranges)
                print("\n".join([str((tr["trip_id"], tr["duration"],
                    arrow.get(tr["start_ts"]).to(self.spec_details.eval_tz),
                    arrow.get(tr["end_ts"]).to(self.spec_details.eval_tz)))
                    for tr in curr_eval_trips_ranges]))
                r["evaluation_trip_ranges"] = curr_eval_trips_ranges

    def fill_accuracy_control_section_ranges(self):
        for phoneOS, phone_map in self.accuracy_control_maps.items():
            curr_control_transitions = [t["data"] for t in phone_map[EVAL_TRANSITION]] # from control phone
            curr_evaluation_ranges = phone_map["evaluation_ranges"] # from this phone
            trip_type_check = lambda t: t["transition"] in ["START_EVALUATION_SECTION", "STOP_EVALUATION_SECTION", 6, 7]
            trip_time_check = lambda t, r: t["ts"] >= r["start_ts"] and t["ts"] <= r["end_ts"]
            for i, r in enumerate(curr_evaluation_ranges):
                # We have to get the evaluation details from one of the evaluation phones
                for i, tr in enumerate(r["evaluation_trip_ranges"]):
                    curr_eval_sections_transitions = [t for t in curr_control_transitions if trip_type_check(t) and trip_time_check(t, tr)]
                    # print("\n".join([str((t["transition"], t["trip_id"], t["ts"], arrow.get(t["ts"]).to(eval_tz))) for t in curr_eval_trips_transitions]))
                    # print(len(curr_eval_trips_transitions))
                    curr_eval_sections_ranges = PhoneView.transitions_to_ranges(
                        curr_eval_sections_transitions,
                        "START_EVALUATION_SECTION", "STOP_EVALUATION_SECTION", 6, 7,
                        self.spec_details.eval_end_ts)
                    print("%s: Found %s sections for evaluation %s" % (phoneOS, len(curr_eval_sections_ranges), tr["trip_id"]))
                    # print(curr_eval_sections_ranges)
                    print("\n".join([str((sr["trip_id"], sr["duration"],
                        arrow.get(sr["start_ts"]).to(self.spec_details.eval_tz),
                        arrow.get(sr["end_ts"]).to(self.spec_details.eval_tz)))
                        for sr in curr_eval_sections_ranges]))
                    tr["evaluation_section_ranges"] = curr_eval_sections_ranges

    def copy_trip_ranges_to_other_accuracy_control(self):
        evaluation_ranges_map = {}
        for phoneOS, phone_map in self.accuracy_control_maps.items():
            for r in phone_map["evaluation_ranges"]:
                if r["trip_id"] not in evaluation_ranges_map:
                    evaluation_ranges_map[r["trip_id"]] = {}
                # Must not copy/deepcopy here because we rely on setting
                # the trip ranges into here and have that show up in the
                # overall map
                evaluation_ranges_map[r["trip_id"]][phoneOS] = r

        # print(evaluation_ranges_map.keys())
        for range_id, range_phone_map in evaluation_ranges_map.items():
            trip_counts = [(phoneOS, len(r["evaluation_trip_ranges"]))
                            for phoneOS, r in range_phone_map.items()]
            nonzero_trip_counts = [tc for tc in trip_counts if tc[1] != 0]
            # Either we have one temporal ground truth or we have all
            print("Before copying found %d/%d phones with ground truth for experiment of size %d" %\
                (len(nonzero_trip_counts), len(trip_counts), len(evaluation_ranges_map.items())))

            assert len(nonzero_trip_counts) == 1 or\
                len(nonzero_trip_counts) == len(trip_counts),\
                "Found %d/%d phones with ground truth in experiment of size %d" %\
                    (len(nonzero_counts), len(trip_counts), len(evaluation_ranges_map.items()))

            if len(nonzero_trip_counts) == 1:
                phoneOS_with_ground_truth = nonzero_trip_counts[0][0]
                ground_truthed_trip_ranges = range_phone_map[phoneOS_with_ground_truth]["evaluation_trip_ranges"]
                print("Uncopied ground truth of length %d on found on phone %s" %
                    (len(ground_truthed_trip_ranges), phoneOS_with_ground_truth))
                # print("Ground truthed trip ranges = %s" % ground_truthed_trip_ranges)
            else:
                phoneOS_with_ground_truth = None
                print("No uncopied ground truth found!")

            for phoneOS, r in range_phone_map.items():
                if phoneOS_with_ground_truth is not None and phoneOS != phoneOS_with_ground_truth:
                    print("Copying %d ranges to %s, %s" % (len(ground_truthed_trip_ranges), phoneOS, r["trip_id"]))
                    r["evaluation_trip_ranges"] = copy.deepcopy(ground_truthed_trip_ranges)

            trip_counts = [(phoneOS, len(r["evaluation_trip_ranges"]))
                            for phoneOS, r in range_phone_map.items()]
            nonzero_trip_counts = [tc for tc in trip_counts if tc[1] != 0]
            print("After copying found %d/%d phones with ground truth for experiment of size %d" %\
                (len(nonzero_trip_counts), len(trip_counts), len(evaluation_ranges_map.items())))
            assert len(nonzero_trip_counts) == len(trip_counts),\
                "Found %d/%d phones with ground truth even after copy!" %\
                    (len(nonzero_trip_counts), len(trip_counts))

    def copy_trip_ranges_to_eval_power_maps(self):
        for phoneOS in self.accuracy_control_maps.keys():
            matching_accuracy_control_map = self.accuracy_control_maps[phoneOS]
            matching_eval_power_maps = self.phone_view_map[phoneOS]
            print(matching_eval_power_maps.keys())
            for phone_label, phone_map in matching_eval_power_maps.items():
                if phone_map == matching_accuracy_control_map:
                    print("Found accuracy control, skipping copy")
                    continue
                curr_eval_evaluation_ranges = phone_map["evaluation_ranges"]
                curr_accuracy_evaluation_ranges = matching_accuracy_control_map["evaluation_ranges"]
                assert len(curr_eval_evaluation_ranges) == len(curr_accuracy_evaluation_ranges)
                for i, (re, ra) in enumerate(zip(curr_eval_evaluation_ranges, curr_accuracy_evaluation_ranges)):
                    accuracy_eval_trips_ranges = ra["evaluation_trip_ranges"] # from this phone
                    # print(accuracy_eval_trips_ranges)
                    print("%s: Copying %s accuracy trips to %s, before = %s" % (phoneOS, phone_label, len(accuracy_eval_trips_ranges),
                        len(re["evaluation_trip_ranges"]) if "evaluation_trip_ranges" in re else 0))
                    re["evaluation_trip_ranges"] = copy.deepcopy(accuracy_eval_trips_ranges)
                    # print(re["evaluation_trip_ranges"])
                    # print(curr_eval_trips_ranges)
                    print("\n".join([str((tr["trip_id"], tr["duration"],
                        arrow.get(tr["start_ts"]).to(self.spec_details.eval_tz),
                        arrow.get(tr["end_ts"]).to(self.spec_details.eval_tz)))
                        for tr in re["evaluation_trip_ranges"]]))

    # copy the subset of r[key] that matches the query to tr[key]
    @staticmethod
    def _copy_subset(r, tr, key, query):
        if len(r[key]) > 0:
            tr[key] = r[key].query(query)
        else:
            # since there is no data, we don't need to select a subset
            tr[key] = r[key]

    @staticmethod
    def _query_for_seg(segment):
        return "ts > %s & ts <= %s" % (segment["start_ts"] - TIME_SYNC_FUZZ,
                                segment["end_ts"] + TIME_SYNC_FUZZ)

    def fill_trip_specific_battery_and_locations(self):
        for phoneOS, phone_map in self.phone_view_map.items(): # android, ios
            for phone_label in phone_map:
                print("Filling label %s for OS %s" % (phone_label, phoneOS))
                for r in phone_map[phone_label]["evaluation_ranges"]:
                    # print(r["battery_df"].head())
                    for tr in r["evaluation_trip_ranges"]:
                        query = PhoneView._query_for_seg(tr)
                        # print("%s %s %s" % (phone_label, tr["trip_id"], query))
                        # print(r["battery_df"].query(query).head())
                        PhoneView._copy_subset(r, tr, "battery_df", query)
                        # print(80 * '~')
                        # print(tr["battery_df"])
                        # print(80 * "-")
                        PhoneView._copy_subset(r, tr, "location_df", query)
                        PhoneView._copy_subset(r, tr, "filtered_location_df", query)
                        PhoneView._copy_subset(r, tr, "motion_activity_df", query)
                        PhoneView._copy_subset(r, tr, "transition_df", query)
                        for sr in tr["evaluation_section_ranges"]:
                            query = PhoneView._query_for_seg(sr)
                            # print("%s %s %s" % (phone_label, tr["trip_id"], query))
                            # print(r["battery_df"].query(query).head())
                            PhoneView._copy_subset(tr, sr, "battery_df", query)
                            # print(80 * '~')
                            # print(tr["battery_df"])
                            # print(80 * "-")
                            PhoneView._copy_subset(tr, sr, "location_df", query)
                            PhoneView._copy_subset(r, tr, "filtered_location_df", query)
                            PhoneView._copy_subset(tr, sr, "motion_activity_df", query)
                            PhoneView._copy_subset(tr, sr, "transition_df", query)
    #
    # END: Imported from Validate_calibration_*.ipynb
    #
