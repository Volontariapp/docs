"""Simulation de la formule de points d'evenement (docs/scoring/03-formule.md).

Usage : python3 -I docs/scoring/scripts/simulate.py
Tous les chiffres de docs/scoring/04-exemples-et-simulations.md sont issus de ce script.
"""

E = 0.3
CAP_FACTOR = 2.0  # chaque part est bornee a +100 % de la moyenne P / N
MIN_ATTENDEES_FOR_ORGANIZER_POINTS = 3
FORMULA_VERSION = 1


def pool(n, alpha, beta):
    fill = min(1.0, n / beta) if beta else 0.0
    return n * 100 * alpha * (1 + fill)


def organizer_points(n, alpha, beta):
    if n < MIN_ATTENDEES_FOR_ORGANIZER_POINTS:
        return 0
    fill = min(1.0, n / beta) if beta else 0.0
    return int(150 * alpha * (1 + fill) + 0.5)


def shares(n, p, e=E, cap=True):
    """Parts reelles : poids i^-e, plafond 2P/N, exces redistribue (water-filling)."""
    w = [i ** -e for i in range(1, n + 1)]
    out = [0.0] * n
    free = list(range(n))
    budget = p
    limit = CAP_FACTOR * p / n if cap else float("inf")
    while free:
        total = sum(w[i] for i in free)
        over = [i for i in free if budget * w[i] / total > limit + 1e-12]
        if not over:
            for i in free:
                out[i] = budget * w[i] / total
            break
        for i in over:
            out[i] = limit
            budget -= limit
        free = [i for i in free if i not in over]
    return out


def largest_remainder(values, p):
    base = [int(v) for v in values]
    missing = int(round(p)) - sum(base)
    order = sorted(range(len(values)), key=lambda i: (-(values[i] - base[i]), i))
    for i in order[:missing]:
        base[i] += 1
    return base


def points(n, alpha, beta, e=E, cap=True):
    p = pool(n, alpha, beta)
    return largest_remainder(shares(n, p, e, cap), p), p


def pct(x):
    return f"{x:+.0f} %"


CASES = [
    ("Atelier", "2 h", 5, 5, 1.0),
    ("Ramassage", "4 h", 20, 20, 1.5),
    ("Nettoyage", "24 h", 50, 50, 2.5),
    ("Remplissage partiel", "4 h", 10, 40, 1.5),
    ("Festival", "week-end", 200, 200, 4.0),
]


def main():
    print("## Section 1 : cas calcules (plafond +100 %, plus grand reste)")
    for name, dur, n, beta, alpha in CASES:
        pts, p = points(n, alpha, beta)
        avg = p / n
        picks = [r for r in (1, 3, 10, 50, 100) if r <= n] + [n]
        shown = " / ".join(str(pts[r - 1]) for r in picks)
        tied = sum(1 for v in pts if v == pts[0])
        assert sum(pts) == round(p)
        assert all(a >= b for a, b in zip(pts, pts[1:]))
        print(
            f"{name} | {dur} | N={n} | beta={beta} | alpha={alpha} | P={p:.0f} | "
            f"moy={avg:.0f} | createur={organizer_points(n, alpha, beta)} | "
            f"rangs {picks} -> {shown} | 1er {pct((pts[0] / avg - 1) * 100)} | "
            f"dernier {pct((pts[-1] / avg - 1) * 100)} | ex-aequo au sommet={tied} | somme={sum(pts)}"
        )

    print("\n## Formule pure sans plafond (reference de l'ancien tableau)")
    for name, dur, n, beta, alpha in CASES:
        pts, p = points(n, alpha, beta, cap=False)
        print(f"{name} | rang1={pts[0]} | 1er {pct((pts[0] / (p / n) - 1) * 100)} | dernier={pts[-1]}")

    print("\n## Section 3 : ecart du 1er a la moyenne selon l'exposant (sans plafond)")
    for e in (0.30, 0.20, 0.15, 0.10):
        row = []
        for n in (5, 10, 20, 50, 200):
            s = shares(n, 1.0, e, cap=False)
            row.append(pct((s[0] * n - 1) * 100))
        print(f"e={e:.2f} | " + " | ".join(row))

    print("\n## Section 3 : meme tableau avec plafond +100 %, e=0,3")
    row = []
    for n in (5, 10, 20, 50, 200):
        s = shares(n, 1.0, E, cap=True)
        row.append(pct((s[0] * n - 1) * 100))
    print("e=0.30 plafonne | " + " | ".join(row))

    print("\n## Section 4 : cas particuliers (1 h, alpha=1,0)")
    for n, beta in ((0, 5), (1, 5), (2, 50), (3, 50)):
        if n == 0:
            print(f"N=0 | participants 0 | createur {organizer_points(0, 1.0, beta)}")
            continue
        pts, p = points(n, 1.0, beta)
        print(f"N={n}, beta={beta} | P={p:.0f} | points={pts} | createur={organizer_points(n, 1.0, beta)}")


if __name__ == "__main__":
    main()
