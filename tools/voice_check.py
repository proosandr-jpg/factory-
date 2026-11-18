"""Объективная проверка синтезированного голоса против эталона.

Что считает:
  * близость тембра — косинус между усреднёнными log-mel векторами (40 полос);
  * интонацию — медиану и разброс основного тона (F0) в полутонах;
  * «роботизированность» по косвенным признакам — разброс F0 и разброс энергии.

Это прокси, а не приговор: на слух всё равно надо проверить. Но если тембр
далёк от эталона или F0 почти не меняется — слышно будет сразу.

Запуск:
    python tools/voice_check.py assets/voice/reference.wav output/audio/gen.wav
"""

import sys
import wave

import numpy as np

TARGET_SR = 16000
N_MELS = 40
FRAME = 0.025
HOP = 0.010


def read_wav(path, target_sr=TARGET_SR):
    with wave.open(path) as w:
        sr = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())

    if width == 2:
        data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        data = np.frombuffer(raw, dtype=np.uint8).astype(np.float32)
        data = (data - 128.0) / 128.0

    if channels > 1:
        data = data.reshape(-1, channels).mean(axis=1)

    if sr != target_sr:
        n_new = int(round(len(data) * target_sr / sr))
        x_old = np.linspace(0, 1, len(data), endpoint=False)
        x_new = np.linspace(0, 1, n_new, endpoint=False)
        data = np.interp(x_new, x_old, data).astype(np.float32)
        sr = target_sr
    return data, sr


def _frame_signal(x, sr, frame=FRAME, hop=HOP):
    n = int(frame * sr)
    step = int(hop * sr)
    if len(x) < n:
        return np.zeros((0, n), dtype=np.float32)
    count = 1 + (len(x) - n) // step
    idx = np.arange(n)[None, :] + step * np.arange(count)[:, None]
    return x[idx]


def _mel_filterbank(sr, n_fft, n_mels=N_MELS, fmin=40, fmax=7600):
    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + f / 700.0)

    def mel2hz(m):
        return 700.0 * (10.0 ** (m / 2595.0) - 1.0)

    mels = np.linspace(hz2mel(fmin), hz2mel(fmax), n_mels + 2)
    hz = mel2hz(mels)
    freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)
    fb = np.zeros((n_mels, len(freqs)), dtype=np.float32)
    for i in range(n_mels):
        lo, center, hi = hz[i], hz[i + 1], hz[i + 2]
        left = (freqs - lo) / max(center - lo, 1e-9)
        right = (hi - freqs) / max(hi - center, 1e-9)
        fb[i] = np.clip(np.minimum(left, right), 0, None)
    return fb


def logmel_vector(x, sr=TARGET_SR):
    frames = _frame_signal(x, sr)
    if frames.shape[0] == 0:
        return None, 0
    frames = frames * np.hamming(frames.shape[1])
    n_fft = 1 << int(np.ceil(np.log2(frames.shape[1])))
    spec = np.abs(np.fft.rfft(frames, n=n_fft, axis=1))
    fb = _mel_filterbank(sr, n_fft)
    mel = np.log(spec @ fb.T + 1e-8)
    return mel.mean(axis=0), frames.shape[0]


def f0_track(x, sr=TARGET_SR, fmin=60, fmax=350):
    frame = int(0.04 * sr)
    hop = int(0.01 * sr)
    if len(x) < frame:
        return np.array([])
    lags = np.arange(int(sr / fmax), int(sr / fmin))
    values = []
    for start in range(0, len(x) - frame, hop):
        seg = x[start:start + frame]
        if np.sqrt(np.mean(seg ** 2)) < 0.005:
            continue
        seg = seg - seg.mean()
        ac = np.correlate(seg, seg, mode="full")[frame - 1:]
        if ac[0] <= 0:
            continue
        ac = ac / ac[0]
        window = ac[lags]
        if len(window) == 0:
            continue
        peak = window.max()
        if peak < 0.35:
            continue
        values.append(sr / lags[int(np.argmax(window))])
    return np.array(values, dtype=np.float32)


def describe(path):
    x, sr = read_wav(path)
    mel, n_frames = logmel_vector(x, sr)
    f0 = f0_track(x, sr)
    energy = np.sqrt(np.mean(_frame_signal(x, sr) ** 2, axis=1)) if len(x) else np.array([0.0])

    return {
        "path": path,
        "duration": round(len(x) / sr, 2),
        "frames": n_frames,
        "mel": mel,
        "f0_median": round(float(np.median(f0)), 1) if len(f0) else None,
        "f0_std_semitones": round(float(np.std(12 * np.log2(f0 / np.median(f0)))), 2) if len(f0) else None,
        "energy_cv": round(float(np.std(energy) / (np.mean(energy) + 1e-9)), 3),
    }


def compare(reference_path, generated_path):
    ref = describe(reference_path)
    gen = describe(generated_path)

    sim = None
    if ref["mel"] is not None and gen["mel"] is not None:
        a, b = ref["mel"], gen["mel"]
        sim = float(a @ b / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

    print(f"эталон:     {ref['path']}")
    print(f"  длительность {ref['duration']} c | F0 медиана {ref['f0_median']} Гц | "
          f"разброс F0 {ref['f0_std_semitones']} полутона")
    print(f"синтез:     {gen['path']}")
    print(f"  длительность {gen['duration']} c | F0 медиана {gen['f0_median']} Гц | "
          f"разброс F0 {gen['f0_std_semitones']} полутона")
    print()
    print(f"тембр (косинус log-mel): {sim:.3f}" if sim is not None else "тембр: не посчитан")
    print(f"энергия (коэф. вариации): эталон {ref['energy_cv']} / синтез {gen['energy_cv']}")

    if sim is not None:
        if sim > 0.9:
            verdict = "тембр близок к эталону"
        elif sim > 0.75:
            verdict = "тембр похож, но слышимая разница возможна"
        else:
            verdict = "тембр далёк от эталона — клонирование не сработало"
        print(f"вывод по тембру: {verdict}")
    return {"similarity": sim, "reference": ref, "generated": gen}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    compare(sys.argv[1], sys.argv[2])
