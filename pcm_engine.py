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
        sc = s["hz"] / mfr
        if abs(sc - round(sc)) > 0.001 and sc > 1:
            msgs.append({"type": "error", "msg": f"[{s['name']}] Supercom ratio {sc:.3f} is not integer (§2.5)"})

    # SFID recommendation
    has_subcom = any(s["hz"] < mfr for s in config.get("sensors", []))
    if has_subcom and sfid_count == 0:
        msgs.append({"type": "warning", "msg": "Subcommutated parameters exist → SFID recommended (§2.4)"})

    if not msgs:
        msgs.append({"type": "info", "msg": "IRIG-106 validation passed"})

    return msgs


def _calc_total_used(config: dict) -> dict:
    """Calculate total used word positions per minor frame.

    Returns dict with sensor/digital/bit/subcom counts and total.
    Subcom params share word positions across Z minor frames,
    so they consume fewer positions than their raw EA count.
    """
    frame_hz = config["frame_hz"]
    B = config["bits_per_word"]
    Z = config["minor_count"]
    mfr = frame_hz * Z  # minor frame rate

    sensor_words = 0   # non-subcom sensor words per minor
    digital_words = 0  # non-subcom digital words per minor
    bit_words = 0
    subcom_slots = 0   # total frame-slots needed by subcom params

    for s in config.get("sensors", []):
        if s["hz"] < mfr and Z > 1:
            # Subcommutated: appears Z/ratio times per major frame
            ratio = max(1, round(mfr / s["hz"]))
            subcom_slots += s["ch"] * (Z / ratio)
        else:
            sc = max(1, round(s["hz"] / mfr))
            sensor_words += s["ch"] * sc

    for d in config.get("digital", []):
        ch_per_sample = math.ceil(d["bits"] / B)
        if d["hz"] < mfr and Z > 1:
            ratio = max(1, round(mfr / d["hz"]))
            subcom_slots += ch_per_sample * (Z / ratio)
        else:
            sc = max(1, round(d["hz"] / mfr))
            digital_words += ch_per_sample * sc

    for b in config.get("bit_data", []):
        bit_words += math.ceil(b["bytes"] / (B / 8))

    # Subcom positions: each position has Z slots, pack subcom params into them
    subcom_positions = math.ceil(subcom_slots / Z) if Z > 1 else 0
    total = sensor_words + digital_words + bit_words + subcom_positions

    return {
        "sensor": sensor_words,
        "digital": digital_words,
        "bit": bit_words,
        "subcom_positions": subcom_positions,
        "subcom_params": int(subcom_slots) if Z > 1 else 0,
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
        is_subcom = s["hz"] < mfr and Z > 1
        sc = 1 if is_subcom else max(1, round(s["hz"] / mfr))
        sub_ratio = max(1, round(mfr / s["hz"])) if is_subcom else 0
        for ea in range(s["ch"]):
            params.append({
                "name": f"{s['name']}_{ea + 1}" if s["ch"] > 1 else s["name"],
                "type": s["type"],
                "category": "sensor",
                "hz": s["hz"],
                "supercom": sc,
                "subcom_ratio": sub_ratio,
                "dau": s.get("dau", "MDAU"),
                "note": s.get("note", ""),
                "source": s,
            })

    for d in digital_data:
        ch_count = math.ceil(d["bits"] / B)
        is_subcom = d["hz"] < mfr and Z > 1
        sc = 1 if is_subcom else max(1, round(d["hz"] / mfr))
        sub_ratio = max(1, round(mfr / d["hz"])) if is_subcom else 0
        for ci in range(ch_count):
            params.append({
                "name": f"{d['name']}_{ci + 1}" if ch_count > 1 else d["name"],
                "type": d["type"],
                "category": "digital",
                "hz": d["hz"],
                "supercom": sc,
                "subcom_ratio": sub_ratio,
                "dau": d.get("dau", "MDAU"),
                "note": d.get("note", ""),
                "source": d,
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

    Supercommutation (sc > 1):
      - Frame data area divided into max_sc equal slots.
      - Each copy of a supercom channel is placed in one slot,
        evenly spaced across the frame.
      - If a target slot is full, the copy is placed in the nearest
        available position — channels are NEVER silently dropped.

    Subcommutation (subcom_ratio > 1, requires Z > 1):
      - Each subcom word position is shared by multiple parameters
        appearing at equal intervals across minor frames (every R frames).
      - Subcom positions are taken from the same available-position pool
        as normal params, so they naturally spread throughout the frame
        rather than clustering at the end.

    Both rules apply simultaneously when Z > 1 and max_sc > 1.
    """
    super_params = [p for p in params if p["supercom"] > 1]
    normal_params = [p for p in params if p["supercom"] == 1
                     and p.get("subcom_ratio", 0) == 0]
    subcom_params = [p for p in params if p.get("subcom_ratio", 0) > 0]

    super_params.sort(key=lambda p: (-p["supercom"], p["dau"], p["type"], p["name"]))
    normal_params.sort(key=lambda p: (p["dau"], p["type"], p["name"]))
    subcom_params.sort(key=lambda p: (p["subcom_ratio"], p["dau"], p["name"]))

    # Slot width for equal supercom spacing
    # (data_words // max_sc guarantees each copy lands in its own slot)
    slot_width = data_words // max_sc if max_sc > 1 else data_words

    # Boolean availability map — True means the word position is free
    avail = [False] * W
    for i in range(overhead, W):
        avail[i] = True

    # fixed[word_pos] = cell — identical in every minor frame
    fixed: dict[int, dict] = {}

    def claim(pos, cell):
        fixed[pos] = cell
        avail[pos] = False

    def first_avail(start, end):
        for i in range(start, min(end, W)):
            if avail[i]:
                return i
        return None

    # ── Supercom: slot-based equal spacing ──
    # A param with sc copies needs one copy in each of sc target slots.
    # target_slots are sc evenly-spaced indices out of max_sc.
    for p in super_params:
        sc = p["supercom"]
        target_slots = [round(i * max_sc / sc) for i in range(sc)]
        for slot_idx in target_slots:
            slot_start = overhead + slot_idx * slot_width
            slot_end   = min(slot_start + slot_width, W)
            pos = first_avail(slot_start, slot_end)
            if pos is None:
                # Target slot full — find nearest available in whole data area
                pos = first_avail(overhead, W)
            if pos is not None:
                claim(pos, _make_cell_from_param(p))

    # ── Normal (1×): fill slot 0, overflow to anywhere ──
    slot0_end = min(overhead + slot_width, W)
    for p in normal_params:
        pos = first_avail(overhead, slot0_end)
        if pos is None:
            pos = first_avail(overhead, W)
        if pos is not None:
            claim(pos, _make_cell_from_param(p))

    # ── Subcom: schedule into remaining available positions ──
    # Available positions are spread throughout the frame at this point,
    # so subcom slots will be interleaved — not clustered at the end.
    # Each position holds Z "slots" (one per minor frame); params with
    # ratio=R occupy every R-th slot (equal frame-spacing).
    subcom_schedule: list[dict] = []  # [{position, slots:{mf_idx: param}}]

    for p in subcom_params:
        ratio = p["subcom_ratio"]
        placed = False

        # Try to share an existing subcom position
        for sched in subcom_schedule:
            for offset in range(ratio):
                frames_hit = list(range(offset, Z, ratio))
                if all(f not in sched["slots"] for f in frames_hit):
                    for f in frames_hit:
                        sched["slots"][f] = p
                    placed = True
                    break
            if placed:
                break

        if not placed:
            pos = first_avail(overhead, W)
            if pos is not None:
                sched: dict = {"position": pos, "slots": {}}
                for offset in range(ratio):
                    frames_hit = list(range(offset, Z, ratio))
                    if all(f not in sched["slots"] for f in frames_hit):
                        for f in frames_hit:
                            sched["slots"][f] = p
                        break
                subcom_schedule.append(sched)
                avail[pos] = False

    # ── Build Z minor frames ──
    frames = []
    for mf_idx in range(Z):
        frame = [None] * W

        # SYNC
        for i in range(sync_count):
            frame[i] = _make_cell("SYNC", "SYNC", "system", "#FF4444")
        # SFID (value = minor frame index when Z > 1)
        for i in range(sfid_count):
            cell = _make_cell("SFID", "SFID", "system", "#CC0000")
            if Z > 1:
                cell["note"] = f"MF#{mf_idx}"
            frame[sync_count + i] = cell

        # Fixed params — identical in every minor frame
        for pos, cell in fixed.items():
            frame[pos] = dict(cell)

        # Subcom — different param per minor frame, same word position
        for sched in subcom_schedule:
            word_pos = sched["position"]
            p = sched["slots"].get(mf_idx)
            if p is not None:
                cell = _make_cell_from_param(p)
                cell["subcom"] = True
                cell["subcom_ratio"] = p["subcom_ratio"]
                frame[word_pos] = cell
            else:
                frame[word_pos] = _make_cell("RSVD", "RSVD", "reserved",
                                              "#F5F5F5", note="subcom spare")

        # Fill gaps with RESERVED
        for i in range(W):
            if frame[i] is None:
                frame[i] = _make_cell("RSVD", "RSVD", "reserved", "#F5F5F5")

        label = f"MF {mf_idx} (SFID={mf_idx})" if Z > 1 else "Minor Frame"
        entry: dict = {"label": label, "cells": frame}
        if max_sc > 1:
            entry["slot_width"] = slot_width
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
        is_subcom = s["hz"] < mfr and Z > 1
        if is_subcom:
            sub_ratio = max(1, round(mfr / s["hz"]))
            pcm_ch = s["ch"]  # subcom shares positions
            result.append({
                "idx": ch_idx,
                "category": "Analog Sensor",
                "type": s["type"],
                "name": s["name"],
                "hz": s["hz"],
                "ea": s["ch"],
                "supercom": 0,
                "subcom_ratio": sub_ratio,
                "pcm_ch": pcm_ch,
                "dau": s.get("dau", ""),
                "note": f"1/{sub_ratio} subcom" + (f" {s.get('note', '')}" if s.get('note') else ""),
            })
        else:
            sc = max(1, round(s["hz"] / mfr))
            pcm_ch = s["ch"] * sc
            result.append({
                "idx": ch_idx,
                "category": "Analog Sensor",
                "type": s["type"],
                "name": s["name"],
                "hz": s["hz"],
                "ea": s["ch"],
                "supercom": sc,
                "subcom_ratio": 0,
                "pcm_ch": pcm_ch,
                "dau": s.get("dau", ""),
                "note": s.get("note", ""),
            })
        ch_idx += pcm_ch

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
                "name": d["name"],
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
                "name": d["name"],
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
        if s["hz"] < mfr and Z > 1:
            ratio = max(1, round(mfr / s["hz"]))
            subcom_slots += s["ch"] * (Z / ratio)
        else:
            sc = max(1, round(s["hz"] / mfr))
            max_sc = max(max_sc, sc)
            total_data_ch += s["ch"] * sc

    for d in digital_data:
        ch_count = math.ceil(d["bits"] / B)
        if d["hz"] < mfr and Z > 1:
            ratio = max(1, round(mfr / d["hz"]))
            subcom_slots += ch_count * (Z / ratio)
        else:
            sc = max(1, round(d["hz"] / mfr))
            max_sc = max(max_sc, sc)
            total_data_ch += ch_count * sc

    for b in bit_data:
        total_data_ch += math.ceil(b["bytes"] / (B / 8))

    # Add subcom positions
    if Z > 1:
        total_data_ch += math.ceil(subcom_slots / Z)

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
