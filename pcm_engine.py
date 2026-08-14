"""
PCM Channel Allocation Engine - IRIG 106 Chapter 4 Compliant
Optimal channel table generation for telemetry systems.
"""
import math
from typing import Any

# ── IRIG-106 Constants ──
IRIG = {
    "MAX_Z": 256,
    "MAX_BITS_C1": 8192,
    "MAX_WORDS_C1": 1024,
    "MAX_BPW_C1": 16,
    "MAX_BR_C1": 5_000_000,
    "MIN_BR": 10,
    "SYNC_MIN_BITS": 16,
    "SYNC_MAX_BITS": 33,
}


def pcm_class(W: int, B: int, Z: int, bitrate: float) -> str:
    if (W * B > IRIG["MAX_BITS_C1"] or W > IRIG["MAX_WORDS_C1"]
            or B > IRIG["MAX_BPW_C1"] or bitrate > IRIG["MAX_BR_C1"]):
        return "Class II"
    return "Class I"


def calc_bitrate(W: int, B: int, Z: int, frame_hz: float) -> float:
    return W * B * Z * frame_hz


def calc_sync_bits(sync_pattern: str, bits_per_word: int) -> int:
    parts = [s.strip() for s in sync_pattern.split(",") if s.strip()]
    return len(parts) * bits_per_word


def _sensor_groups(s: dict) -> list[dict]:
    """Return channel groups for a sensor entry.

    Supports two formats:
      New: {"channels": [{"count": 4, "hz": 800}, {"count": 8, "hz": 50}]}
      Old: {"hz": 800, "ch": 8}   → converted to single group
    """
    if "channels" in s and s["channels"]:
        return s["channels"]
    return [{"count": s.get("ch", 1), "hz": s.get("hz", 50)}]


def _sensor_total_ch(s: dict) -> int:
    """Total channel count for a sensor entry."""
    return sum(g["count"] for g in _sensor_groups(s))


def _plan_subcom_columns(ratio_counts: dict[int, int], budget: int) -> dict[int, int]:
    """Decide how many word positions each subcom ratio group may occupy.

    Horizontal-first — the layout the frame aims for whenever it can afford
    it: every subcom channel owns a dedicated word position and is sampled
    at minor frames 0, R, 2R, …

    When the frame cannot afford one position per channel, channels sharing
    a ratio R stack vertically inside one position — IRIG-106 subframe
    commutation, where phase p occupies the minor frames with mf % R == p.
    One position then carries up to R channels.

    Returns {ratio: columns}. The sum exceeds ``budget`` only when even the
    fully stacked minimum does not fit; the caller reports that as overflow.
    """
    cols = {r: max(1, math.ceil(n / r)) for r, n in ratio_counts.items() if n > 0}
    spare = budget - sum(cols.values())
    while spare > 0:
        widenable = [r for r, c in cols.items() if c < ratio_counts[r]]
        if not widenable:
            break
        # Unstack the most densely packed group first
        r = max(widenable, key=lambda k: (ratio_counts[k] / cols[k], k))
        cols[r] += 1
        spare -= 1
    return cols


def validate_config(config: dict) -> list[dict]:
    """Validate configuration against IRIG-106 Chapter 4 rules."""
    msgs = []
    W = config["words_per_minor"]
    B = config["bits_per_word"]
    Z = config["minor_count"]
    frame_hz = config["frame_hz"]
    sync_count = config["sync_count"]
    sfid_count = config["sfid_count"]
    sync_pattern = config.get("sync_pattern", "0xFAF3")

    br = calc_bitrate(W, B, Z, frame_hz)
    sb = calc_sync_bits(sync_pattern, B)
    cls = pcm_class(W, B, Z, br)
    avail = W - sync_count - sfid_count  # per minor frame
    used_info = _calc_total_used(config)
    used = used_info["total"]
    rem = avail - used

    # Critical errors
    if Z > IRIG["MAX_Z"]:
        msgs.append({"type": "error", "msg": f"Minor Frame count {Z} > 256 (IRIG-106 §4.2)"})
    if sb < IRIG["SYNC_MIN_BITS"] or sb > IRIG["SYNC_MAX_BITS"]:
        msgs.append({"type": "error", "msg": f"SYNC pattern {sb} bit - allowed 16~33 bit (§4.3)"})
    if br < IRIG["MIN_BR"]:
        msgs.append({"type": "error", "msg": f"Bit rate < 10 bps (§4.8)"})
    if rem < 0:
        msgs.append({"type": "error", "msg": f"Channel overflow: required {used} > available {avail}"})

    # Class II warnings
    if cls == "Class II":
        if W * B > IRIG["MAX_BITS_C1"]:
            msgs.append({"type": "warning", "msg": f"Frame bits {W * B:,} > 8,192 → Class II (§4.2)"})
        if W > IRIG["MAX_WORDS_C1"]:
            msgs.append({"type": "warning", "msg": f"Word count {W:,} > 1,024 → Class II (§4.2)"})
        if B > IRIG["MAX_BPW_C1"]:
            msgs.append({"type": "warning", "msg": f"Word length {B} bit > 16 → Class II (§4.2)"})
        if br > IRIG["MAX_BR_C1"]:
            msgs.append({"type": "warning", "msg": f"Bit rate {br / 1e6:.2f} Mbps > 5 Mbps → Class II, Range approval required (§4.8)"})

    # Supercommutation validation (use minor frame rate = frame_hz * Z)
    mfr = frame_hz * Z
    for s in config.get("sensors", []):
        for g in _sensor_groups(s):
            sc = g["hz"] / mfr
            if abs(sc - round(sc)) > 0.001 and sc > 1:
                msgs.append({"type": "error", "msg": f"[{s['name']}] Supercom ratio {sc:.3f} is not integer (§2.5)"})

    # SFID recommendation
    has_subcom = any(
        g["hz"] < mfr
        for s in config.get("sensors", [])
        for g in _sensor_groups(s)
    )
    if has_subcom and sfid_count == 0:
        msgs.append({"type": "warning", "msg": "Subcommutated parameters exist → SFID recommended (§2.4)"})

    if not msgs:
        msgs.append({"type": "info", "msg": "IRIG-106 validation passed"})

    return msgs


def _calc_total_used(config: dict) -> dict:
    """Calculate total used word positions per minor frame.

    Returns dict with sensor/digital/bit/subcom counts and total.
    Subcom channels are laid out horizontally first — one dedicated word
    position each — and stack vertically into shared, phase-separated
    positions only when the frame runs out of room (see
    :func:`_plan_subcom_columns`).
    """
    frame_hz = config["frame_hz"]
    B = config["bits_per_word"]
    Z = config["minor_count"]
    mfr = frame_hz * Z  # minor frame rate

    sensor_words = 0    # non-subcom sensor words per minor
    digital_words = 0   # non-subcom digital words per minor
    bit_words = 0
    sub_by_ratio: dict[int, int] = {}  # subcom ratio → channel count
    subcom_appearances = 0  # total subcom appearances per major frame

    for s in config.get("sensors", []):
        for g in _sensor_groups(s):
            cnt, hz = g["count"], g["hz"]
            if hz < mfr and Z > 1:
                ratio = max(1, round(mfr / hz))
                sub_by_ratio[ratio] = sub_by_ratio.get(ratio, 0) + cnt
                subcom_appearances += cnt * (Z // ratio)
            else:
                sc = max(1, round(hz / mfr))
                sensor_words += cnt * sc

    for d in config.get("digital", []):
        ch_per_sample = math.ceil(d["bits"] / B)
        if d["hz"] < mfr and Z > 1:
            ratio = max(1, round(mfr / d["hz"]))
            sub_by_ratio[ratio] = sub_by_ratio.get(ratio, 0) + ch_per_sample
            subcom_appearances += ch_per_sample * (Z // ratio)
        else:
            sc = max(1, round(d["hz"] / mfr))
            digital_words += ch_per_sample * sc

    for b in config.get("bit_data", []):
        bit_words += math.ceil(b["bytes"] / (B / 8))

    fixed_words = sensor_words + digital_words + bit_words
    overhead = config.get("sync_count", 0) + config.get("sfid_count", 0)
    budget = max(0, config.get("words_per_minor", 0) - overhead - fixed_words)
    subcom_channels = sum(sub_by_ratio.values())

    # Committed footprint: the irreducible number of positions, reached when
    # every ratio group is fully stacked. The allocator spreads wider than
    # this whenever the frame has room (it keeps bulk packets contiguous),
    # but those extra positions collapse again as soon as another parameter
    # needs them — so they are spare capacity, not consumed words.
    subcom_positions = sum(math.ceil(n / r) for r, n in sub_by_ratio.items())
    subcom_spread = sum(_plan_subcom_columns(sub_by_ratio, budget).values())

    total = fixed_words + subcom_positions

    return {
        "sensor": sensor_words,
        "digital": digital_words,
        "bit": bit_words,
        "subcom_positions": subcom_positions,
        "subcom_spread": subcom_spread,
        "subcom_channels": subcom_channels,
        "subcom_stacked": subcom_channels > subcom_spread,
        "subcom_params": subcom_appearances,
        "total": total,
    }


def allocate_channels(config: dict) -> dict:
    """
    Generate optimal PCM channel allocation following IRIG-106 Ch.4.

    Algorithm:
    1. Place SYNC + SFID at fixed positions
    2. Calculate supercom ratios for all parameters
    3. Determine slot structure for supercommutation
    4. Place supercommutated parameters with even spacing
    5. Place normal (1x) parameters, grouped by DAU
    6. Handle subcommutation across minor frames
    7. Fill remaining as RESERVED
    """
    W = config["words_per_minor"]
    B = config["bits_per_word"]
    Z = config["minor_count"]
    frame_hz = config["frame_hz"]
    sync_count = config["sync_count"]
    sfid_count = config["sfid_count"]
    sync_pattern = config.get("sync_pattern", "0xFAF3")
    bit_repr = config.get("bit_repr", "NRZ-L")

    sensors = config.get("sensors", [])
    digital_data = config.get("digital", [])
    bit_data = config.get("bit_data", [])

    br = calc_bitrate(W, B, Z, frame_hz)
    cls = pcm_class(W, B, Z, br)
    sb = calc_sync_bits(sync_pattern, B)
    overhead = sync_count + sfid_count
    data_words = W - overhead  # available data words per minor frame

    # ── Categorize parameters by supercom/subcom ratio (use minor frame rate) ──
    mfr = frame_hz * Z  # minor frame rate
    params = []
    for s in sensors:
        device = s.get("device", "M")
        slot = s.get("slot", "S1")
        module_name = s.get("name", "MOD")
        ch_num = 1  # sequential across all groups
        for g in _sensor_groups(s):
            hz = g["hz"]
            count = g["count"]
            is_subcom = hz < mfr and Z > 1
            sc = 1 if is_subcom else max(1, round(hz / mfr))
            sub_ratio = max(1, round(mfr / hz)) if is_subcom else 0
            for _ in range(count):
                base_label = f"{device}_{slot}_{module_name}-{ch_num:02d}"
                params.append({
                    "name": base_label,
                    "type": s["type"],
                    "category": "sensor",
                    "hz": hz,
                    "supercom": sc,
                    "subcom_ratio": sub_ratio,
                    "dau": s.get("dau", device),
                    "note": s.get("note", ""),
                    "source": s,
                })
                ch_num += 1

    # Digital label format: {device}_{slot}_{type}-{dt_idx:02d}-{word_idx:02d}
    # dt_idx: sequential number among entries sharing the same (device, slot) slot
    _dt_counters: dict = {}
    for d in digital_data:
        ch_count = math.ceil(d["bits"] / B)
        is_subcom = d["hz"] < mfr and Z > 1
        sc = 1 if is_subcom else max(1, round(d["hz"] / mfr))
        sub_ratio = max(1, round(mfr / d["hz"])) if is_subcom else 0
        device = d.get("device", "M")
        slot = d.get("slot", "S1")
        type_name = d.get("type", "DIG").strip()

        group_key = (device, slot)      # grouped by slot, not module name
        _dt_counters[group_key] = _dt_counters.get(group_key, 0) + 1
        dt_idx = _dt_counters[group_key]

        for ci in range(ch_count):
            word_idx = ci + 1
            label = f"{device}_{slot}_{type_name}-{dt_idx:02d}-{word_idx:02d}"
            params.append({
                "name": label,
                "type": d["type"],
                "category": "digital",
                "hz": d["hz"],
                "supercom": sc,
                "subcom_ratio": sub_ratio,
                "dau": d.get("dau", device),
                "note": d.get("note", ""),
                "source": d,
                "label_complete": True,   # label is final — no occurrence suffix
            })

    for b in bit_data:
        ch_count = math.ceil(b["bytes"] / (B / 8))
        for ci in range(ch_count):
            params.append({
                "name": f"VL{b['vl']}_{ci + 1}" if ch_count > 1 else f"VL{b['vl']}",
                "type": "BIT",
                "category": "bit",
                "hz": mfr,
                "supercom": 1,
                "subcom_ratio": 0,
                "dau": "BIT",
                "note": b.get("note", ""),
                "source": b,
            })

    # ── Determine max supercom ratio ──
    max_sc = max((p["supercom"] for p in params), default=1)

    # ── Build minor frame layout (unified allocation) ──
    result_frames = _allocate_frames(
        W, Z, data_words, overhead, sync_count, sfid_count, max_sc, params
    )

    # ── Calculate statistics (per minor frame) ──
    total_avail = data_words  # available data words per minor frame
    used_info = _calc_total_used(config)
    total_used = used_info["total"]
    total_reserved = total_avail - total_used

    return {
        "success": True,
        "frames": result_frames,
        "stats": {
            "bitrate": br,
            "bitrate_mbps": round(br / 1e6, 3),
            "pcm_class": cls,
            "bit_repr": bit_repr,
            "sync_bits": sb,
            "sync_pattern": sync_pattern,
            "words_per_minor": W,
            "bits_per_word": B,
            "minor_count": Z,
            "frame_hz": frame_hz,
            "minor_frame_rate": mfr,
            "total_available": total_avail,
            "total_used": total_used,
            "total_reserved": total_reserved,
            "usage_pct": round(total_used / total_avail * 100, 1) if total_avail > 0 else 0,
            "sensor_ch": used_info["sensor"],
            "digital_ch": used_info["digital"],
            "bit_ch": used_info["bit"],
            "subcom_positions": used_info["subcom_positions"],
            "subcom_spread": used_info["subcom_spread"],
            "subcom_channels": used_info["subcom_channels"],
            "subcom_stacked": used_info["subcom_stacked"],
            "subcom_params": used_info["subcom_params"],
            "max_supercom": max_sc,
            "overhead_per_minor": overhead,
        },
        "validation": validate_config(config),
        "param_list": _build_param_list(config, frame_hz, B),
    }


def _allocate_frames(W, Z, data_words, overhead, sync_count, sfid_count,
                     max_sc, params):
    """
    Unified frame allocation for all modes (IRIG-106 Ch.4 compliant).

    Supercommutation rule (IRIG-106 §4):
      "Supercommutated samples shall be evenly spaced."
      spacing = W // N  (based on TOTAL frame width)

      For each supercom parameter, ALL N copies must be placed at
      exactly equal intervals. We scan every possible starting offset
      p0 in [overhead, overhead+spacing) and select the first offset
      where ALL positions p0, p0+spacing, …, p0+(N-1)*spacing are free.
      This avoids the "nearest available" fallback that would break
      equal spacing. If a single starting offset cannot satisfy all
      copies, the channel is placed at whatever free positions remain
      (overflow — validate_config will flag this).

    Subcommutation rule (IRIG-106 §4):
      Each subcommutated channel gets its own dedicated word position.
      It appears at that position in every R-th minor frame
      (frames 0, R, 2R, …) where R = subcom_ratio.
      All other minor frames at that position are RSVD.
      No sharing between different subcom channels — each channel owns
      exactly one word position throughout the major frame.
    """
    super_params = [p for p in params if p["supercom"] > 1]
    normal_params = [p for p in params if p["supercom"] == 1
                     and p.get("subcom_ratio", 0) == 0]
    subcom_params = [p for p in params if p.get("subcom_ratio", 0) > 0]

    # High-ratio params first so they anchor the frame layout
    super_params.sort(key=lambda p: (-p["supercom"], p["dau"], p["type"], p["name"]))
    normal_params.sort(key=lambda p: (p["dau"], p["type"], p["name"]))
    subcom_params.sort(key=lambda p: (p["subcom_ratio"], p["dau"], p["name"]))

    # Availability map — True = free
    avail = [False] * W
    for i in range(overhead, W):
        avail[i] = True

    fixed: dict[int, dict] = {}  # word_pos → cell (same in every minor frame)

    def claim(pos: int, cell: dict) -> None:
        fixed[pos] = cell
        avail[pos] = False

    def first_avail(start, end):
        for i in range(start, min(end, W)):
            if avail[i]:
                return i
        return None

    # ── Supercom: intelligent equidistant placement ──
    # For each channel, scan starting offsets until finding one where
    # every copy lands on a free slot.  This preserves equal spacing
    # even when higher-ratio params have already claimed some positions.
    # Each copy gets a unique occurrence suffix: base-1, base-2, …, base-N
    for p in super_params:
        sc = p["supercom"]
        spacing = W // sc       # IRIG-106: evenly spaced across full frame W

        placed = False
        # Scan all possible starting offsets within one spacing period
        for p0 in range(overhead, overhead + spacing):
            positions = [p0 + k * spacing for k in range(sc)]
            if all(pos < W and avail[pos] for pos in positions):
                for k, pos in enumerate(positions):
                    cell = _make_cell_from_param(p)
                    if p.get("label_complete"):
                        cell["name"] = p["name"]          # digital: label already final
                    else:
                        cell["name"] = f"{p['name']}-{k + 1}"  # sensor: occurrence index
                    claim(pos, cell)
                placed = True
                break

        if not placed:
            # Overflow: place at any remaining free positions
            # (validate_config will report the overflow)
            pos = first_avail(overhead, W)
            if pos is not None:
                cell = _make_cell_from_param(p)
                if p.get("label_complete"):
                    cell["name"] = p["name"]
                else:
                    cell["name"] = f"{p['name']}-1"
                claim(pos, cell)

    # ── Normal (1×): fill any remaining data-area position ──
    for p in normal_params:
        pos = first_avail(overhead, W)
        if pos is not None:
            cell = _make_cell_from_param(p)
            if p.get("label_complete"):
                cell["name"] = p["name"]      # digital: label already final
            else:
                cell["name"] = f"{p['name']}-1"   # sensor: occurrence = 1
            claim(pos, cell)

    # ── Subcom: horizontal first, vertical stacking when space runs out ──
    # Preferred layout gives every subcom channel its own word position,
    # sampled at frames 0, R, 2R, …  When the frame cannot afford that,
    # channels of the same ratio share a position and are separated by SFID
    # phase (frames where mf % R == phase) — IRIG-106 subframe commutation,
    # so one position carries up to R channels.
    subcom_by_pos: dict[int, list[dict]] = {}

    if subcom_params:
        by_ratio: dict[int, list[dict]] = {}
        for p in subcom_params:
            by_ratio.setdefault(p["subcom_ratio"], []).append(p)

        budget = sum(1 for i in range(overhead, W) if avail[i])
        cols = _plan_subcom_columns({r: len(v) for r, v in by_ratio.items()},
                                    budget)

        for ratio in sorted(by_ratio):
            plist = by_ratio[ratio]
            positions: list[int] = []
            for _ in range(min(cols[ratio], len(plist))):
                pos = first_avail(overhead, W)
                if pos is None:
                    break           # frame full — overflow
                avail[pos] = False  # reserve this position
                positions.append(pos)
            if not positions:
                continue
            n_cols = len(positions)
            for j, p in enumerate(plist):
                # Fill across the positions first, then wrap to the next
                # phase — horizontal rows fill before stacking downward.
                pos = positions[j % n_cols]
                phase = (j // n_cols) % ratio
                subcom_by_pos.setdefault(pos, []).append({
                    "param": p,
                    "phase": phase,
                    "frames": set(range(phase, Z, ratio)),
                })

    # ── Build Z minor frames ──
    frames = []
    for mf_idx in range(Z):
        frame: list = [None] * W

        for i in range(sync_count):
            frame[i] = _make_cell("SYNC", "SYNC", "system", "#FF4444")
        for i in range(sfid_count):
            cell = _make_cell("SFID", "SFID", "system", "#CC0000")
            if Z > 1:
                cell["note"] = f"MF#{mf_idx}"
            frame[sync_count + i] = cell

        for pos, cell in fixed.items():
            frame[pos] = dict(cell)

        # A subcom position may carry several phase-separated channels;
        # at most one of them is active in any given minor frame.
        for word_pos, scheds in subcom_by_pos.items():
            cell = None
            for sched in scheds:
                if mf_idx not in sched["frames"]:
                    continue
                p = sched["param"]
                cell = _make_cell_from_param(p)
                if p.get("label_complete"):
                    cell["name"] = p["name"]       # digital: label already final
                else:
                    cell["name"] = f"{p['name']}-1"   # sensor: occurrence = 1
                cell["subcom"] = True
                cell["subcom_ratio"] = p["subcom_ratio"]
                cell["subcom_phase"] = sched["phase"]
                break
            frame[word_pos] = cell or _make_cell(
                "RSVD", "RSVD", "reserved", "#F5F5F5", note="subcom spare")

        for i in range(W):
            if frame[i] is None:
                frame[i] = _make_cell("RSVD", "RSVD", "reserved", "#F5F5F5")

        label = f"MF {mf_idx} (SFID={mf_idx})" if Z > 1 else "Minor Frame"
        entry: dict = {"label": label, "cells": frame}
        if max_sc > 1:
            entry["slot_width"] = W // max_sc   # for UI slot-boundary display
            entry["max_sc"] = max_sc
        frames.append(entry)

    return frames


# ── Color maps ──
SENSOR_COLORS = {
    "RTD": "#FFD700", "STR3W": "#90EE90", "STR4W": "#5DBD5D",
    "PRS": "#6495ED", "ACCICP": "#FF8C00", "ACCDC": "#FFB347",
    "VOLTAGE": "#87CEEB", "TC": "#FF69B4", "PIEZO": "#9370DB",
    "ACOUSTIC": "#C0A0FF", "ETC": "#C8C8C8",
}
DIGITAL_COLORS = {
    "DISCRETE": "#B0C4DE", "ARINC429": "#85C1E9", "1553B": "#82E0AA",
    "RS422": "#F0B27A", "LVDT": "#D7BDE2", "RESOLVER": "#A9CCE3",
    "ENCODER": "#A9DFBF", "DIGITAL": "#AED6F1",
}


def _get_color(param: dict) -> str:
    if param["category"] == "sensor":
        return SENSOR_COLORS.get(param["type"], "#C8C8C8")
    elif param["category"] == "digital":
        return DIGITAL_COLORS.get(param["type"], "#AED6F1")
    elif param["category"] == "bit":
        return "#A0A0A0"
    return "#F5F5F5"


def _make_cell(name, type_, category, color, note=""):
    return {
        "name": name, "type": type_, "category": category,
        "color": color, "note": note,
    }


def _make_cell_from_param(param):
    return {
        "name": param["name"],
        "type": param["type"],
        "category": param["category"],
        "color": _get_color(param),
        "dau": param.get("dau", ""),
        "hz": param.get("hz", 0),
        "supercom": param.get("supercom", 1),
        "note": param.get("note", ""),
    }


def _find_next_empty(frame, start, end):
    """Find the next empty position from start up to (but not including) end."""
    for i in range(start, end):
        if frame[i] is None:
            return i
    return None


def _build_param_list(config: dict, frame_hz: float, B: int) -> list[dict]:
    """Build a flat list of all parameters for export."""
    Z = config.get("minor_count", 1)
    mfr = frame_hz * Z  # minor frame rate
    result = []
    ch_idx = 1

    for s in config.get("sensors", []):
        groups = _sensor_groups(s)
        total_ch = _sensor_total_ch(s)
        # Build a summary entry per sensor (groups summarised in note)
        group_notes = []
        total_pcm_ch = 0
        for g in groups:
            hz, cnt = g["hz"], g["count"]
            is_subcom = hz < mfr and Z > 1
            if is_subcom:
                sub_ratio = max(1, round(mfr / hz))
                group_notes.append(f"{cnt}ch@Sub1/{sub_ratio}")
                total_pcm_ch += cnt
            else:
                sc = max(1, round(hz / mfr))
                group_notes.append(f"{cnt}ch@{hz}Hz{'×'+str(sc) if sc>1 else ''}")
                total_pcm_ch += cnt * sc
        comm_summary = ", ".join(group_notes)
        note_str = (s.get("note", "") + " | " if s.get("note") else "") + comm_summary
        result.append({
            "idx": ch_idx,
            "category": "Analog Sensor",
            "type": s["type"],
            "name": s["name"],
            "hz": ", ".join(str(g["hz"]) for g in groups) if len(groups) > 1 else str(groups[0]["hz"]),
            "ea": total_ch,
            "supercom": 0,
            "subcom_ratio": 0,
            "pcm_ch": total_pcm_ch,
            "dau": s.get("dau", ""),
            "note": note_str,
        })
        ch_idx += total_pcm_ch

    for d in config.get("digital", []):
        ch_count = math.ceil(d["bits"] / B)
        is_subcom = d["hz"] < mfr and Z > 1
        if is_subcom:
            sub_ratio = max(1, round(mfr / d["hz"]))
            pcm_ch = ch_count
            result.append({
                "idx": ch_idx,
                "category": "Digital Data",
                "type": d["type"],
                "name": d.get("name", d.get("type", "DIG")),
                "hz": d["hz"],
                "bits": d["bits"],
                "supercom": 0,
                "subcom_ratio": sub_ratio,
                "pcm_ch": pcm_ch,
                "dau": d.get("dau", ""),
                "note": f"1/{sub_ratio} subcom" + (f" {d.get('note', '')}" if d.get('note') else ""),
            })
        else:
            sc = max(1, round(d["hz"] / mfr))
            pcm_ch = ch_count * sc
            result.append({
                "idx": ch_idx,
                "category": "Digital Data",
                "type": d["type"],
                "name": d.get("name", d.get("type", "DIG")),
                "hz": d["hz"],
                "bits": d["bits"],
                "supercom": sc,
                "subcom_ratio": 0,
                "pcm_ch": pcm_ch,
                "dau": d.get("dau", ""),
                "note": d.get("note", ""),
            })
        ch_idx += pcm_ch

    for b in config.get("bit_data", []):
        ch_count = math.ceil(b["bytes"] / (B / 8))
        result.append({
            "idx": ch_idx,
            "category": "BIT Data",
            "type": "BIT",
            "name": f"VL{b['vl']}",
            "bytes": b["bytes"],
            "pcm_ch": ch_count,
            "supercom": 1,
            "subcom_ratio": 0,
            "dau": "BIT",
            "note": b.get("note", ""),
        })
        ch_idx += ch_count

    return result


def auto_calculate_frame_size(config: dict) -> dict:
    """
    Auto-calculate optimal frame size (W, Z) based on parameters.

    Strategy:
    1. Find the maximum supercom ratio
    2. Calculate minimum words needed for all parameters
    3. Add overhead (sync + sfid)
    4. Round up to a convenient size
    5. Check IRIG-106 limits
    """
    frame_hz = config["frame_hz"]
    B = config["bits_per_word"]
    sync_count = config["sync_count"]
    sfid_count = config["sfid_count"]
    overhead = sync_count + sfid_count

    sensors = config.get("sensors", [])
    digital_data = config.get("digital", [])
    bit_data = config.get("bit_data", [])
    Z = config.get("minor_count", 1)
    mfr = frame_hz * Z  # minor frame rate

    # Calculate total data words needed per minor frame
    max_sc = 1
    total_data_ch = 0
    subcom_slots = 0

    for s in sensors:
        for g in _sensor_groups(s):
            hz, cnt = g["hz"], g["count"]
            if hz < mfr and Z > 1:
                subcom_slots += cnt
            else:
                sc = max(1, round(hz / mfr))
                max_sc = max(max_sc, sc)
                total_data_ch += cnt * sc

    for d in digital_data:
        ch_count = math.ceil(d["bits"] / B)
        if d["hz"] < mfr and Z > 1:
            subcom_slots += ch_count
        else:
            sc = max(1, round(d["hz"] / mfr))
            max_sc = max(max_sc, sc)
            total_data_ch += ch_count * sc

    for b in bit_data:
        total_data_ch += math.ceil(b["bytes"] / (B / 8))

    # Add subcom positions (one dedicated word position per subcom channel)
    if Z > 1:
        total_data_ch += subcom_slots

    # Minimum W
    min_W = total_data_ch + overhead

    # Round up to a multiple of max_sc for even slot sizing
    if max_sc > 1:
        data_per_slot = math.ceil(total_data_ch / max_sc)
        min_W = data_per_slot * max_sc + overhead

    # Add 5-10% margin for spare channels
    W = math.ceil(min_W * 1.05)

    # Round to convenient number (multiple of 8 or 16)
    W = math.ceil(W / 16) * 16
    W = max(W, overhead + 4)

    Z = 1  # Default single minor frame

    br = calc_bitrate(W, B, Z, frame_hz)
    cls = pcm_class(W, B, Z, br)

    return {
        "words_per_minor": W,
        "minor_count": Z,
        "bitrate": br,
        "pcm_class": cls,
        "max_supercom": max_sc,
        "total_data_ch": total_data_ch,
        "margin_pct": round((W - overhead - total_data_ch) / max(total_data_ch, 1) * 100, 1),
    }
