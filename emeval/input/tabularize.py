import numpy as np
import pandas as pd


def constant_valued_column(name: str, value, indices) -> pd.DataFrame:
    return pd.DataFrame({name: np.full(indices.size, value)}, index=indices)


def tabularize_pv_map(pv_map: dict) -> dict:
    df_map = dict()

    for phone_os, phones in pv_map.items():
        for phone_label, phone_map in phones.items():
            pk = {"phone_label": phone_label, "role": phone_map["role"]}
            for i, r in enumerate(phone_map["calibration_ranges"] + phone_map["evaluation_ranges"]):
                for df_label, df in {k: v for k, v in r.items() if isinstance(v, pd.DataFrame)}.items():
                    curr_pk = pk.copy()

                    if r in phone_map["calibration_ranges"]:
                        curr_pk.update({"range_type": "calibration", "range_index": i})
                    elif r in phone_map["evaluation_ranges"]:
                        curr_pk.update({"range_type": "evaluation", "range_index": i - len(phone_map["calibration_ranges"])})

                    curr_pk.update({k: v for k, v in r.items()
                                    if not (isinstance(v, pd.DataFrame) or isinstance(v, list) or isinstance(v, dict))})

                    update_df = df.assign(**curr_pk).rename(
                        columns={"start_ts": "gt_start_ts", "end_ts": "gt_end_ts", "duration": "gt_duration"})

                    if r in phone_map["evaluation_ranges"]:
                        for i_etr, etr in enumerate(r["evaluation_trip_ranges"]):
                            if df_label in etr:
                                if "trip_range_id" not in update_df.columns:
                                    update_df = pd.concat(
                                        [update_df,
                                         constant_valued_column("trip_range_id", etr["trip_id"], etr[df_label].index),
                                         constant_valued_column("trip_range_id_base", etr["trip_id_base"], etr[df_label].index),
                                         constant_valued_column("trip_range_run", etr["trip_run"], etr[df_label].index),
                                         constant_valued_column("trip_range_gt_start_ts", etr["start_ts"], etr[df_label].index),
                                         constant_valued_column("trip_range_gt_end_ts", etr["end_ts"], etr[df_label].index),
                                         constant_valued_column("trip_range_gt_duration", etr["duration"], etr[df_label].index),
                                         constant_valued_column("trip_range_index", i_etr, etr[df_label].index)],
                                        axis=1)
                                else:
                                    update_df.at[etr[df_label].index, "trip_range_id"] = etr["trip_id"]
                                    update_df.at[etr[df_label].index, "trip_range_id_base"] = etr["trip_id_base"]
                                    update_df.at[etr[df_label].index, "trip_range_run"] = etr["trip_run"]
                                    update_df.at[etr[df_label].index, "trip_range_gt_start_ts"] = etr["start_ts"]
                                    update_df.at[etr[df_label].index, "trip_range_gt_end_ts"] = etr["end_ts"]
                                    update_df.at[etr[df_label].index, "trip_range_gt_duration"] = etr["duration"]
                                    update_df.at[etr[df_label].index, "trip_range_index"] = i_etr

                            for i_esr, esr in enumerate(etr["evaluation_section_ranges"]):
                                if df_label in esr:
                                    if "section_range_id" not in update_df.columns:
                                        update_df = pd.concat(
                                            [update_df,
                                             constant_valued_column("section_range_id", esr["trip_id"], esr[df_label].index),
                                             constant_valued_column("section_range_id_base", esr["trip_id_base"], esr[df_label].index),
                                             constant_valued_column("section_range_run", esr["trip_run"], esr[df_label].index),
                                             constant_valued_column("section_range_gt_start_ts", esr["start_ts"], esr[df_label].index),
                                             constant_valued_column("section_range_gt_end_ts", esr["end_ts"], esr[df_label].index),
                                             constant_valued_column("section_range_gt_duration", esr["duration"], esr[df_label].index),
                                             constant_valued_column("section_range_index", i_esr, esr[df_label].index)],
                                            axis=1)
                                    else:
                                        update_df.at[esr[df_label].index, "section_range_id"] = esr["trip_id"]
                                        update_df.at[esr[df_label].index, "section_range_id_base"] = esr["trip_id_base"]
                                        update_df.at[esr[df_label].index, "section_range_run"] = esr["trip_run"]
                                        update_df.at[esr[df_label].index, "section_range_gt_start_ts"] = esr["start_ts"]
                                        update_df.at[esr[df_label].index, "section_range_gt_end_ts"] = esr["end_ts"]
                                        update_df.at[esr[df_label].index, "section_range_gt_duration"] = esr["duration"]
                                        update_df.at[esr[df_label].index, "section_range_index"] = i_esr

                    for ts_col in [c for c in update_df.columns.tolist() if "ts" in c]:
                        update_df[ts_col] = update_df[ts_col].astype(float)

                    if phone_os not in df_map:
                        df_map[phone_os] = dict()

                    if df_label not in df_map[phone_os]:
                        df_map[phone_os][df_label] = update_df
                    else:
                        df_map[phone_os][df_label] = pd.concat([df_map[phone_os][df_label], update_df], ignore_index=True)
                        if "ts" in (curr_df := df_map[phone_os][df_label]):
                            df_map[phone_os][df_label] = curr_df.sort_values(by=["ts"])
                        else:
                            df_map[phone_os][df_label] = curr_df.sort_values(by=["gt_start_ts"])

    return df_map
