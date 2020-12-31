import os
import pandas as pd

import socceraction.spadl as _spadl
from socceraction.spadl.base import _add_dribbles

bodyparts = _spadl.bodyparts
bodyparts_df = _spadl.bodyparts_df

actiontypes = _spadl.actiontypes + [
    "receival",
    "interception",
    "out",
    "offside",
    "goal",
    "owngoal",
    "yellow_card",
    "red_card",
    "corner",
    "freekick",
]


def actiontypes_df():
    return pd.DataFrame(
        list(enumerate(actiontypes)), columns=["type_id", "type_name"]
    )


def add_names(actions) -> pd.DataFrame:
    return (
        actions
        .drop(columns=['type_name', 'bodypart_name'], errors='ignore')
        .merge(actiontypes_df(), how="left")
        .merge(bodyparts_df(), how="left")
    )


def convert_to_atomic(actions: pd.DataFrame) -> pd.DataFrame:
    actions = actions.copy()
    actions = _extra_from_passes(actions)
    actions = _add_dribbles(actions)  # for some reason this adds more dribbles
    actions = _extra_from_shots(actions)
    actions = _extra_from_fouls(actions)
    actions = _convert_columns(actions)
    actions = _simplify(actions)
    return actions


def _extra_from_passes(actions: pd.DataFrame) -> pd.DataFrame:
    next_actions = actions.shift(-1)
    same_team = actions.team_id == next_actions.team_id

    passlike = [
        "pass",
        "cross",
        "throw_in",
        "freekick_short",
        "freekick_crossed",
        "corner_crossed",
        "corner_short",
        "clearance",
        "goalkick",
    ]
    pass_ids = list(_spadl.actiontypes.index(ty) for ty in passlike)

    interceptionlike = [
        "interception",
        "tackle",
        "keeper_punch",
        "keeper_save",
        "keeper_claim",
        "keeper_pick_up",
    ]
    interception_ids = list(_spadl.actiontypes.index(ty) for ty in interceptionlike)

    samegame = actions.game_id == next_actions.game_id
    sameperiod = actions.period_id == next_actions.period_id
    # samephase = next_actions.time_seconds - actions.time_seconds < max_pass_duration
    extra_idx = (
        actions.type_id.isin(pass_ids)
        & samegame
        & sameperiod  # & samephase
        & ~next_actions.type_id.isin(interception_ids)
    )

    prev = actions[extra_idx]
    nex = next_actions[extra_idx]

    extra = pd.DataFrame()
    extra["game_id"] = prev.game_id
    extra["original_event_id"] = prev.original_event_id
    extra["period_id"] = prev.period_id
    extra["action_id"] = prev.action_id + 0.1
    extra["time_seconds"] = (prev.time_seconds + nex.time_seconds) / 2
    extra["timestamp"] = nex.timestamp
    extra["start_x"] = prev.end_x
    extra["start_y"] = prev.end_y
    extra["end_x"] = prev.end_x
    extra["end_y"] = prev.end_y
    extra["bodypart_id"] = bodyparts.index("foot")
    extra["result_id"] = -1

    offside = prev.result_id == _spadl.results.index("offside")
    out = ((nex.type_id == actiontypes.index("goalkick")) & (~same_team)) | (
        nex.type_id == actiontypes.index("throw_in")
    )
    ar = actiontypes
    extra["type_id"] = -1
    extra["type_id"] = (
        extra.type_id.mask(same_team, ar.index("receival"))
        .mask(~same_team, ar.index("interception"))
        .mask(out, ar.index("out"))
        .mask(offside, ar.index("offside"))
    )
    is_interception = extra["type_id"] == ar.index("interception")
    extra["team_id"] = prev.team_id.mask(is_interception, nex.team_id)
    extra["player_id"] = nex.player_id.mask(out | offside, prev.player_id)

    actions = pd.concat([actions, extra], ignore_index=True, sort=False)
    actions = actions.sort_values(["game_id", "period_id", "action_id"]).reset_index(
        drop=True
    )
    actions["action_id"] = range(len(actions))
    return actions


def _extra_from_shots(actions: pd.DataFrame) -> pd.DataFrame:
    next_actions = actions.shift(-1)

    shotlike = ["shot", "shot_freekick", "shot_penalty"]
    shot_ids = list(_spadl.actiontypes.index(ty) for ty in shotlike)

    samegame = actions.game_id == next_actions.game_id
    sameperiod = actions.period_id == next_actions.period_id

    shot = actions.type_id.isin(shot_ids)
    goal = shot & (actions.result_id == _spadl.results.index("success"))
    owngoal = shot & (actions.result_id == _spadl.results.index("owngoal"))
    next_corner_goalkick = next_actions.type_id.isin(
        [
            actiontypes.index("corner_crossed"),
            actiontypes.index("corner_short"),
            actiontypes.index("goalkick"),
        ]
    )
    out = shot & next_corner_goalkick & samegame & sameperiod

    extra_idx = goal | owngoal | out
    prev = actions[extra_idx]
    nex = next_actions[extra_idx]

    extra = pd.DataFrame()
    extra["game_id"] = prev.game_id
    extra["original_event_id"] = prev.original_event_id
    extra["period_id"] = prev.period_id
    extra["action_id"] = prev.action_id + 0.1
    extra["time_seconds"] = prev.time_seconds  # + nex.time_seconds) / 2
    extra["timestamp"] = prev.timestamp
    extra["start_x"] = prev.end_x
    extra["start_y"] = prev.end_y
    extra["end_x"] = prev.end_x
    extra["end_y"] = prev.end_y
    extra["bodypart_id"] = prev.bodypart_id
    extra["result_id"] = -1
    extra["team_id"] = prev.team_id
    extra["player_id"] = prev.player_id

    ar = actiontypes
    extra["type_id"] = -1
    extra["type_id"] = (
        extra.type_id.mask(goal, ar.index("goal"))
        .mask(owngoal, ar.index("owngoal"))
        .mask(out, ar.index("out"))
    )
    actions = pd.concat([actions, extra], ignore_index=True, sort=False)
    actions = actions.sort_values(["game_id", "period_id", "action_id"]).reset_index(
        drop=True
    )
    actions["action_id"] = range(len(actions))
    return actions


def _extra_from_fouls(actions: pd.DataFrame) -> pd.DataFrame:
    yellow = actions.result_id == _spadl.results.index("yellow_card")
    red = actions.result_id == _spadl.results.index("red_card")

    prev = actions[yellow | red]
    extra = pd.DataFrame()
    extra["game_id"] = prev.game_id
    extra["original_event_id"] = prev.original_event_id
    extra["period_id"] = prev.period_id
    extra["action_id"] = prev.action_id + 0.1
    extra["time_seconds"] = prev.time_seconds  # + nex.time_seconds) / 2
    extra["timestamp"] = prev.timestamp
    extra["start_x"] = prev.end_x
    extra["start_y"] = prev.end_y
    extra["end_x"] = prev.end_x
    extra["end_y"] = prev.end_y
    extra["bodypart_id"] = prev.bodypart_id
    extra["result_id"] = -1
    extra["team_id"] = prev.team_id
    extra["player_id"] = prev.player_id

    ar = actiontypes
    extra["type_id"] = -1
    extra["type_id"] = extra.type_id.mask(yellow, ar.index("yellow_card")).mask(
        red, ar.index("red_card")
    )
    actions = pd.concat([actions, extra], ignore_index=True, sort=False)
    actions = actions.sort_values(["game_id", "period_id", "action_id"]).reset_index(
        drop=True
    )
    actions["action_id"] = range(len(actions))
    return actions


def _convert_columns(actions: pd.DataFrame) -> pd.DataFrame:
    actions["x"] = actions.start_x
    actions["y"] = actions.start_y
    actions["dx"] = actions.end_x - actions.start_x
    actions["dy"] = actions.end_y - actions.start_y
    return actions[
        [
            "game_id",
            "original_event_id",
            "action_id",
            "period_id",
            "time_seconds",
            "timestamp",
            "team_id",
            "player_id",
            "x",
            "y",
            "dx",
            "dy",
            "type_id",
            "bodypart_id",
        ]
    ]


def _simplify(actions: pd.DataFrame) -> pd.DataFrame:
    a = actions
    ar = actiontypes

    cornerlike = ["corner_crossed", "corner_short"]
    corner_ids = list(_spadl.actiontypes.index(ty) for ty in cornerlike)

    freekicklike = ["freekick_crossed", "freekick_short", "shot_freekick"]
    freekick_ids = list(_spadl.actiontypes.index(ty) for ty in freekicklike)

    a["type_id"] = a.type_id.mask(a.type_id.isin(corner_ids), ar.index("corner"))
    a["type_id"] = a.type_id.mask(a.type_id.isin(freekick_ids), ar.index("freekick"))
    return a
