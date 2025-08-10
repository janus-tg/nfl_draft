from config import SCORING
import pandas as pd


def compute_fantasy_points(df: pd.DataFrame) -> pd.Series:
    p = pd.Series(0.0, index=df.index)
    p += df["pass_yds"] * SCORING["pass_yds"]
    p += df["pass_td"] * SCORING["pass_td"]
    p += df["pass_int"] * SCORING["pass_int"]
    p += df["rush_yds"] * SCORING["rush_yds"]
    p += df["rush_td"] * SCORING["rush_td"]
    p += df["rec"] * SCORING["rec"]
    p += df["rec_yds"] * SCORING["rec_yds"]
    p += df["rec_td"] * SCORING["rec_td"]
    p += df["ret_yds"] * SCORING["ret_yds"]
    p += df["ret_td"] * SCORING["ret_td"]
    p += df["two_pt"] * SCORING["two_pt"]
    p += df["fum_lost"] * SCORING["fum_lost"]
    p += df["off_fum_td"] * SCORING["off_fum_td"]
    p += df["fg_miss_0_19"] * SCORING["fg_miss_0_19"]
    p += df["fg_miss_20_29"] * SCORING["fg_miss_20_29"]
    p += df["fg_miss_30_39"] * SCORING["fg_miss_30_39"]
    p += df["fg_miss_40_49"] * SCORING["fg_miss_40_49"]
    p += df["fg_miss_50"] * SCORING["fg_miss_50"]
    p += df["pat_made"] * SCORING["pat_made"]
    p += df["pat_miss"] * SCORING["pat_miss"]
    p += df["fg_yds"] * SCORING["fg_yds"]
    p += df["sack"] * SCORING["sack"]
    p += df["dst_int"] * SCORING["dst_int"]
    p += df["dst_fum_rec"] * SCORING["dst_fum_rec"]
    p += df["dst_td"] * SCORING["dst_td"]
    p += df["dst_safety"] * SCORING["dst_safety"]
    p += df["dst_block_kick"] * SCORING["dst_block_kick"]
    p += df["dst_ret_td"] * SCORING["dst_ret_td"]
    p += df["dst_xp_ret"] * SCORING["dst_xp_ret"]
    pa = df["dst_pa"]
    p += (
        (pa == 0) * SCORING["dst_pa_0"]
        + ((pa >= 1) & (pa <= 6)) * SCORING["dst_pa_1_6"]
        + ((pa >= 7) & (pa <= 13)) * SCORING["dst_pa_7_13"]
        + ((pa >= 14) & (pa <= 20)) * SCORING["dst_pa_14_20"]
        + ((pa >= 21) & (pa <= 27)) * SCORING["dst_pa_21_27"]
        + ((pa >= 28) & (pa <= 34)) * SCORING["dst_pa_28_34"]
        + ((pa >= 35)) * SCORING["dst_pa_35_plus"]
    )
    return p
