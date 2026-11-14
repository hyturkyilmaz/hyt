"""Telifsiz arka plan müziği üretir (tamamen sentez, örnek/sample kullanılmaz).

Kullanım: python3 icerik/araclar/muzik-uret.py <cikti.wav> [sure_sn] [tohum]

Lo-fi / podcast altlığı: 84 BPM, yumuşak elektrik piyano akorları, alt bas,
hafif davul ve plak cızırtısı. Konuşmanın altında %8-10 seviyede kullanılmak
üzere orta frekanslar kısık tutulur. Her tohum farklı akor dizisi ve ritim
varyasyonu üretir; çıktı tamamen özgündür, lisans gerektirmez.
"""
import sys
import wave
import numpy as np

SR = 44100
out = sys.argv[1]
dur = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
seed = int(sys.argv[3]) if len(sys.argv) > 3 else 7
rng = np.random.default_rng(seed)

BPM = 84
beat = 60.0 / BPM
bar = 4 * beat
n = int(dur * SR)
t = np.arange(n) / SR
L = np.zeros(n)
R = np.zeros(n)


def midi(m):
    return 440.0 * 2 ** ((m - 69) / 12)


def env(length, a=0.01, d=0.6, s=0.0, r=0.3):
    """Basit ADSR zarfı, örnek sayısı cinsinden uzunluk."""
    x = np.arange(length) / SR
    e = np.where(x < a, x / a, s + (1 - s) * np.exp(-(x - a) / d))
    tail = int(r * SR)
    if tail and length > tail:
        e[-tail:] *= np.linspace(1, 0, tail)
    return e


def add(buf, start, sig, gain=1.0):
    i = max(0, int(start * SR))
    if i >= n:
        return
    j = min(n, i + len(sig))
    buf[i:j] += gain * sig[: j - i]


def epiano(freq, length):
    x = np.arange(int(length * SR)) / SR
    trem = 1 + 0.08 * np.sin(2 * np.pi * 4.5 * x)
    sig = (np.sin(2 * np.pi * freq * x)
           + 0.35 * np.sin(2 * np.pi * 2 * freq * x) * np.exp(-x * 3)
           + 0.12 * np.sin(2 * np.pi * 3 * freq * x) * np.exp(-x * 6))
    return sig * trem * env(len(x), a=0.008, d=1.4, s=0.25, r=0.4)


# Akor dizileri (MIDI): ii-V-I-vi ailesi, sakin ve "danışman" tonu
PROGS = [
    [[57, 60, 64, 67], [53, 57, 60, 64], [48, 52, 55, 59], [55, 59, 62, 65]],  # Am7 Fmaj7 Cmaj7 G7
    [[50, 53, 57, 60], [55, 59, 62, 65], [48, 52, 55, 59], [57, 60, 64, 67]],  # Dm7 G7 Cmaj7 Am7
    [[53, 57, 60, 64], [52, 55, 59, 62], [50, 53, 57, 60], [48, 52, 55, 59]],  # Fmaj7 Em7 Dm7 Cmaj7
]
prog = PROGS[seed % len(PROGS)]

nbars = int(dur / bar) + 1
for b in range(nbars):
    chord = prog[b % 4]
    t0 = b * bar
    # piyano: akor + hafif arpej
    for k, m in enumerate(chord):
        f = midi(m)
        sig = epiano(f, bar * 0.98)
        pan = 0.35 + 0.1 * k
        add(L, t0 + 0.012 * k, sig, 0.10 * (1 - pan + 0.5))
        add(R, t0 + 0.012 * k, sig, 0.10 * (pan + 0.5))
    if rng.random() < 0.7:
        m = chord[rng.integers(0, 4)] + 12
        add(L, t0 + 2.5 * beat, epiano(midi(m), beat * 1.5), 0.05)
        add(R, t0 + 2.5 * beat, epiano(midi(m), beat * 1.5), 0.07)
    # bas
    root = midi(chord[0] - 24)
    for st, ln in [(0, 1.6), (2, 1.2)]:
        x = np.arange(int(ln * beat * SR)) / SR
        sig = np.sin(2 * np.pi * root * x) * env(len(x), a=0.01, d=0.5, s=0.4, r=0.1)
        add(L, t0 + st * beat, sig, 0.16)
        add(R, t0 + st * beat, sig, 0.16)
    # davul
    for q in range(4):
        tq = t0 + q * beat
        if q in (0, 2) or (q == 3 and rng.random() < 0.3):
            x = np.arange(int(0.25 * SR)) / SR
            f = 110 * np.exp(-x * 30) + 45
            kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-x * 14)
            add(L, tq, kick, 0.11)
            add(R, tq, kick, 0.11)
        if q in (1, 3):
            x = np.arange(int(0.18 * SR)) / SR
            snare = rng.normal(0, 1, len(x)) * np.exp(-x * 22)
            add(L, tq + 0.01, snare, 0.035)
            add(R, tq + 0.01, snare, 0.035)
        for h in (0, 0.5):
            x = np.arange(int(0.05 * SR)) / SR
            hat = np.diff(rng.normal(0, 1, len(x) + 1)) * np.exp(-x * 70)
            g = 0.012 if h else 0.018
            add(L, tq + h * beat + rng.normal(0, 0.006), hat, g * 0.8)
            add(R, tq + h * beat + rng.normal(0, 0.006), hat, g)

# plak cızırtısı
crackle = np.zeros(n)
idx = rng.integers(0, n, int(dur * 12))
crackle[idx] = rng.normal(0, 0.25, len(idx))
L += crackle * 0.3 + rng.normal(0, 0.0015, n)
R += crackle * 0.3 + rng.normal(0, 0.0015, n)


# yumuşak ton: FFT tabanlı alçak geçiren
def lp_fast(x, fc):
    from numpy.fft import rfft, irfft, rfftfreq
    X = rfft(x)
    f = rfftfreq(len(x), 1 / SR)
    X *= 1 / np.sqrt(1 + (f / fc) ** 4)
    return irfft(X, len(x))


L, R = lp_fast(L, 5200), lp_fast(R, 5200)
fade = int(1.5 * SR)
for ch in (L, R):
    ch[:fade] *= np.linspace(0, 1, fade)
    ch[-fade:] *= np.linspace(1, 0, fade)
peak = max(np.abs(L).max(), np.abs(R).max())
L, R = L / peak * 0.89, R / peak * 0.89
pcm = (np.stack([L, R], axis=1) * 32767).astype(np.int16)
with wave.open(out, "wb") as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print(out, f"{dur:.0f} sn, tohum {seed}")
