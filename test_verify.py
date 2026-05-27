"""
검증 스크립트: M + S1, 각 10모듈 구성
- 채널 ID 레이블 형식 검증: {device}_{slot}_{module}-{ch:02d}-{supercom}
- 슈퍼콤 등간격 배치 검증 (중복 없음)
- 서브콤 독립 워드 위치 검증
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pcm_engine import allocate_channels, validate_config

# ── 테스트 설정 ──────────────────────────────────────
# Major: 1 Hz, Z=50, MFR=50 Hz, 16-bit word, 1 Mbps → W≈1280
CONFIG = {
    "frame_hz": 1,
    "minor_count": 50,
    "words_per_minor": 1280,
    "bits_per_word": 16,
    "sync_count": 2,
    "sfid_count": 1,
    "sync_pattern": "0xFAF3, 0x3400",
    "bit_repr": "NRZ-L",
    "sensors": [
        # ── MASTER (M) ── 10 modules ──────────────────
        # S1: 고속 가속도(ICP)   800 Hz → supercom 16x
        {"device":"M", "slot":"S1", "name":"ICP", "type":"ACCICP", "hz":800, "ch":8},
        # S2: 고속 가속도(ICP)   800 Hz → supercom 16x
        {"device":"M", "slot":"S2", "name":"ICP", "type":"ACCICP", "hz":800, "ch":8},
        # S3: 피에조              800 Hz → supercom 16x
        {"device":"M", "slot":"S3", "name":"PZT", "type":"PIEZO",  "hz":800, "ch":8},
        # S4: 피에조              800 Hz → supercom 16x
        {"device":"M", "slot":"S4", "name":"PZT", "type":"PIEZO",  "hz":800, "ch":8},
        # S5: DC 전압            50 Hz → normal 1x
        {"device":"M", "slot":"S5", "name":"DC",  "type":"VOLTAGE","hz":50,  "ch":16},
        # S6: 압력               50 Hz → normal 1x
        {"device":"M", "slot":"S6", "name":"PRS", "type":"PRS",    "hz":50,  "ch":16},
        # S7: 열전대             50 Hz → normal 1x
        {"device":"M", "slot":"S7", "name":"TC",  "type":"TC",     "hz":50,  "ch":16},
        # S8: RTD                50 Hz → normal 1x
        {"device":"M", "slot":"S8", "name":"RTD", "type":"RTD",    "hz":50,  "ch":16},
        # S9: 저속 RTD           10 Hz → subcom (MFR=50, ratio=5)
        {"device":"M", "slot":"S9", "name":"RTD", "type":"RTD",    "hz":10,  "ch":8},
        # S10: 저속 열전대        5 Hz → subcom (MFR=50, ratio=10)
        {"device":"M", "slot":"S10","name":"TC",  "type":"TC",     "hz":5,   "ch":4},

        # ── SLAVE 1 (S1) ── 10 modules ───────────────
        # S1: 스트레인(3선)      50 Hz → normal 1x
        {"device":"S1", "slot":"S1", "name":"STR3","type":"STR3W", "hz":50,  "ch":16},
        # S2: 스트레인(4선)      50 Hz → normal 1x
        {"device":"S1", "slot":"S2", "name":"STR4","type":"STR4W", "hz":50,  "ch":16},
        # S3: 가속도(DC)         50 Hz → normal 1x
        {"device":"S1", "slot":"S3", "name":"ACC", "type":"ACCDC", "hz":50,  "ch":12},
        # S4: DC 전압            50 Hz → normal 1x
        {"device":"S1", "slot":"S4", "name":"DC",  "type":"VOLTAGE","hz":50, "ch":16},
        # S5: 압력               50 Hz → normal 1x
        {"device":"S1", "slot":"S5", "name":"PRS", "type":"PRS",   "hz":50,  "ch":16},
        # S6: 열전대             50 Hz → normal 1x
        {"device":"S1", "slot":"S6", "name":"TC",  "type":"TC",    "hz":50,  "ch":16},
        # S7: RTD                50 Hz → normal 1x
        {"device":"S1", "slot":"S7", "name":"RTD", "type":"RTD",   "hz":50,  "ch":16},
        # S8: 고속 ICP           800 Hz → supercom 16x
        {"device":"S1", "slot":"S8", "name":"ICP", "type":"ACCICP","hz":800, "ch":8},
        # S9: 저속 압력           10 Hz → subcom
        {"device":"S1", "slot":"S9", "name":"PRS", "type":"PRS",   "hz":10,  "ch":8},
        # S10: 음향              800 Hz → supercom 16x
        {"device":"S1", "slot":"S10","name":"ACO", "type":"ACOUSTIC","hz":800,"ch":4},
    ],
    "digital": [],
    "bit_data": [],
}

MFR = CONFIG["frame_hz"] * CONFIG["minor_count"]   # 50 Hz
W   = CONFIG["words_per_minor"]
Z   = CONFIG["minor_count"]


def run():
    print("=" * 70)
    print("PCM 분산형 채널표 검증 — M + S1, 각 10모듈")
    print(f"  MFR={MFR} Hz, W={W} words/minor, Z={Z} minor frames")
    print("=" * 70)

    result = allocate_channels(CONFIG)

    if not result["success"]:
        print("❌ allocate_channels 실패")
        return

    frames = result["frames"]
    stats  = result["stats"]

    # ── 1. 레이블 형식 검증 ─────────────────────────────────
    print("\n[1] 채널 ID 레이블 형식 검증")
    BAD_LABELS = []
    SEEN_LABELS = set()
    ALL_CELL_LABELS = []   # (frame_idx, word_idx, label)

    for fi, frame in enumerate(frames):
        for wi, cell in enumerate(frame["cells"]):
            name = cell.get("name", "")
            if name in ("RSVD", "SYNC", "SFID", ""):
                continue
            ALL_CELL_LABELS.append((fi, wi, name))

            # 포맷 체크: {device}_{slot}_{module}-{ch:02d}-{sc}
            parts = name.split("_")
            if len(parts) < 3:
                BAD_LABELS.append(f"  MF{fi} W{wi+1}: '{name}' — 언더바 구분 불충분")
                continue
            dash_part = parts[-1]  # e.g. "DC-06-1"
            sub = dash_part.split("-")
            if len(sub) != 3:
                BAD_LABELS.append(f"  MF{fi} W{wi+1}: '{name}' — 대시 구분 불일치 ({dash_part})")
                continue
            mod_name, ch_str, sc_str = sub
            if not ch_str.isdigit() or len(ch_str) != 2:
                BAD_LABELS.append(f"  MF{fi} W{wi+1}: '{name}' — 채널 번호 형식 오류 ({ch_str})")
            if not sc_str.isdigit():
                BAD_LABELS.append(f"  MF{fi} W{wi+1}: '{name}' — 슈퍼콤 값 형식 오류 ({sc_str})")

    if BAD_LABELS:
        print(f"  ❌ 형식 오류 {len(BAD_LABELS)}건:")
        for b in BAD_LABELS[:10]:
            print(b)
    else:
        print(f"  ✅ 모든 레이블 형식 정상 (검사 {len(ALL_CELL_LABELS)}개 셀)")

    # ── 2. 슈퍼콤 순번 레이블 + 등간격 배치 검증 ───────────────
    print("\n[2] 슈퍼콤 순번 레이블 및 등간격 배치 검증")

    # 새 형식: 동일 채널(base)의 순번별 위치를 수집
    # e.g. "M_S1_ICP-01" → {1: w_pos1, 2: w_pos2, ..., 16: w_pos16}
    from collections import defaultdict
    frame0 = frames[0]["cells"]

    base_occurrences = defaultdict(dict)   # base → {occurrence: word_idx}
    for wi, cell in enumerate(frame0):
        name = cell.get("name", "")
        if name in ("RSVD", "SYNC", "SFID", ""):
            continue
        # Split off occurrence suffix  e.g. "M_S1_ICP-01-3" → base="M_S1_ICP-01", occ=3
        last_dash = name.rfind("-")
        if last_dash < 0:
            continue
        base = name[:last_dash]
        occ_str = name[last_dash+1:]
        if not occ_str.isdigit():
            continue
        occ = int(occ_str)
        base_occurrences[base][occ] = wi

    super_errors = []
    super_ok = []
    for base, occ_map in base_occurrences.items():
        N = max(occ_map.keys())
        if N == 1:
            continue   # 노말콤/서브콤 — 슈퍼콤 아님

        # 순번 1..N 모두 있는지 확인
        missing = [k for k in range(1, N+1) if k not in occ_map]
        if missing:
            super_errors.append(f"  ❌ {base}: 누락된 순번 {missing}")
            continue

        # 중복 순번 확인
        positions = [occ_map[k] for k in range(1, N+1)]
        expected_spacing = W // N
        gaps = [positions[i+1]-positions[i] for i in range(N-1)]
        equal = all(g == gaps[0] for g in gaps)
        correct = (gaps[0] == expected_spacing)
        if not equal or not correct:
            super_errors.append(
                f"  ❌ {base}: {N}x, positions={[p+1 for p in positions]}, "
                f"gaps={gaps}, expected={expected_spacing}"
            )
        else:
            super_ok.append(
                f"  ✅ {base}: {N}x, spacing={gaps[0]}, "
                f"W[{positions[0]+1}..{positions[-1]+1}]"
            )

    if super_errors:
        print(f"  슈퍼콤 오류 {len(super_errors)}건:")
        for e in super_errors:
            print(e)
    else:
        print(f"  ✅ 슈퍼콤 파라미터 {len(super_ok)}개 모두 등간격 정상")
    for s in super_ok[:8]:   # 처음 8개만 출력
        print(s)
    if len(super_ok) > 8:
        print(f"  ... 외 {len(super_ok)-8}개")

    # ── 3. 슈퍼콤 워드 위치 중복 검사 ────────────────────────
    print("\n[3] MF0 워드 위치 중복 배치 검사")
    used_words = {}   # word_idx → label
    dup_errors = []
    for wi, cell in enumerate(frame0):
        name = cell.get("name", "")
        if name in ("RSVD", ""):
            continue
        if wi in used_words:
            dup_errors.append(
                f"  ❌ W{wi+1}: '{used_words[wi]}' vs '{name}' — 중복!"
            )
        else:
            used_words[wi] = name

    if dup_errors:
        print(f"  ❌ 중복 {len(dup_errors)}건:")
        for e in dup_errors:
            print(e)
    else:
        print(f"  ✅ 중복 없음 (MF0 사용 워드 {len(used_words)}개)")

    # ── 4. 서브콤 독립 위치 검증 ──────────────────────────────
    print("\n[4] 서브콤 독립 워드 위치 검증")
    # 서브콤 채널: MF0에서 나타나는 레이블 중 일부 프레임에서만 사용되는 것
    # 전 프레임을 스캔해서 각 워드 위치가 서브콤인지 확인
    subcom_positions = {}   # word_idx → {set of frame indices with data}
    for fi, frame in enumerate(frames):
        for wi, cell in enumerate(frame["cells"]):
            name = cell.get("name", "")
            sc_flag = cell.get("subcom", False)
            if sc_flag:
                if wi not in subcom_positions:
                    subcom_positions[wi] = {"frames": [], "labels": set()}
                subcom_positions[wi]["frames"].append(fi)
                subcom_positions[wi]["labels"].add(name)

    sub_errors = []
    for wi, info in subcom_positions.items():
        if len(info["labels"]) > 1:
            sub_errors.append(
                f"  ❌ W{wi+1}: 서브콤 위치에 여러 레이블 공유 → {info['labels']}"
            )

    if sub_errors:
        print(f"  ❌ 서브콤 공유 오류 {len(sub_errors)}건:")
        for e in sub_errors:
            print(e)
    else:
        print(f"  ✅ 서브콤 {len(subcom_positions)}개 위치 모두 독립 할당")
    for wi, info in list(subcom_positions.items())[:6]:
        labels = list(info["labels"])
        print(f"     W{wi+1}: {labels[0]}  (등장 {len(info['frames'])}회 / MF{info['frames'][:4]}...)")

    # ── 5. 통계 요약 ──────────────────────────────────────────
    print("\n[5] 채널 할당 통계")
    s = stats
    print(f"  Bit Rate      : {s['bitrate']:,} bps ({s['bitrate_mbps']} Mbps)")
    print(f"  PCM Class     : {s['pcm_class']}")
    print(f"  Words/Minor   : {s['words_per_minor']}")
    print(f"  Minor Frames  : {s['minor_count']}")
    print(f"  MFR           : {s['minor_frame_rate']} Hz")
    print(f"  Overhead/MF   : {s['overhead_per_minor']} words (SYNC+SFID)")
    print(f"  Sensor words  : {s['sensor_ch']}")
    print(f"  Subcom pos.   : {s['subcom_positions']}")
    print(f"  Total used    : {s['total_used']} / {s['total_available']} ({s['usage_pct']}%)")
    print(f"  Reserved      : {s['total_reserved']} words")
    print(f"  Max Supercom  : {s['max_supercom']}x")

    # ── 6. IRIG-106 검증 ──────────────────────────────────────
    print("\n[6] IRIG-106 검증")
    msgs = result["validation"]
    for m in msgs:
        icon = "✅" if m["type"]=="info" else ("⚠️" if m["type"]=="warning" else "❌")
        print(f"  {icon} [{m['type'].upper()}] {m['msg']}")

    # ── 7. 샘플 레이블 출력 (MF0, 첫 60 워드) ────────────────
    print("\n[7] MF0 채널 배치 샘플 (처음 60 워드)")
    cells0 = frames[0]["cells"]
    for wi in range(min(60, len(cells0))):
        cell = cells0[wi]
        name = cell.get("name", "RSVD")
        sc_flag = cell.get("subcom", False)
        sc_mark = " [sub]" if sc_flag else ""
        sc_val  = cell.get("supercom", 1)
        sc_disp = f" {sc_val}x" if sc_val > 1 else ""
        print(f"  W{wi+1:4d}: {name:<25}{sc_disp}{sc_mark}")

    print("\n" + "=" * 70)
    total_errors = len(BAD_LABELS) + len(super_errors) + len(dup_errors) + len(sub_errors)
    if total_errors == 0:
        print("✅ 전체 검증 통과 — 오류 없음")
    else:
        print(f"❌ 검증 실패 — 총 {total_errors}건 오류")
    print("=" * 70)


if __name__ == "__main__":
    run()
