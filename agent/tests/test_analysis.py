import unittest

from lynx_agent.analysis import analyze_notes, detect_key_hypothesis

PPQ = 960
BAR = 3840

NOTE_FIELDS = dict(pan=0, muted=False, finePitch=0, slide=0, porta=0, release=0,
                   modX=0.5, modY=0.5, colour=0, group=0, chance=1.0,
                   velocityRange=0, chanceGroup=0, chanceOne=False, expression={})


def note(key, start, length, velocity=100, channel=0):
    return {"key": key, "start": start, "length": length, "velocity": velocity,
            "channel": channel, **NOTE_FIELDS}


def kick_pattern():
    """4 compassos de four-on-the-floor + fill no fim."""
    notes = []
    for bar in range(3):
        for beat in range(4):
            notes.append(note(36, bar * BAR + beat * PPQ, 240, 110))
    # fill: semicolcheias no último compasso
    for i in range(8):
        notes.append(note(38 + i % 3, 3 * BAR + i * 240, 120, 90 + i * 5))
    return notes


class TestEmpty(unittest.TestCase):
    def test_empty_pattern(self):
        r = analyze_notes([], ppq=PPQ, bar_ticks=BAR)
        self.assertEqual(r["note_count"], 0)
        self.assertTrue(any("vazio" in w for w in r["warnings"]))


class TestDensityAndSpan(unittest.TestCase):
    def test_density_per_bar(self):
        r = analyze_notes(kick_pattern(), ppq=PPQ, bar_ticks=BAR)
        self.assertEqual(r["density"]["per_bar"][:3], [4, 4, 4])
        self.assertEqual(r["density"]["per_bar"][3], 8)
        self.assertEqual(r["span"], {"start": 0, "end": 3 * BAR + 7 * 240 + 120, "ticks": 3 * BAR + 7 * 240 + 120})

    def test_pitch_extension(self):
        r = analyze_notes(kick_pattern(), ppq=PPQ, bar_ticks=BAR)
        self.assertEqual(r["pitch"]["min"], 36)
        self.assertEqual(r["pitch"]["max"], 40)


class TestRhythm(unittest.TestCase):
    def test_all_on_grid(self):
        r = analyze_notes(kick_pattern(), ppq=PPQ, bar_ticks=BAR)
        self.assertEqual(r["rhythm"]["off_grid_count"], 0)

    def test_off_grid_detected(self):
        notes = [note(60, 5, 100), note(62, PPQ, 100)]
        r = analyze_notes(notes, ppq=PPQ, bar_ticks=BAR)
        self.assertEqual(r["rhythm"]["off_grid_count"], 1)


class TestRepetition(unittest.TestCase):
    def test_repeated_bars(self):
        r = analyze_notes(kick_pattern(), ppq=PPQ, bar_ticks=BAR)
        pairs = [rep["bars"] for rep in r["repetition"]["repeated_bars"] if rep["kind"] == "pitch+rhythm"]
        # cada compasso repetido é reportado contra a 1.ª ocorrência
        self.assertIn([0, 1], pairs)
        self.assertIn([0, 2], pairs)
        self.assertNotIn([0, 3], pairs)  # fill difere


class TestOverlaps(unittest.TestCase):
    def test_overlap_on_same_key(self):
        notes = [note(60, 0, 960), note(60, 480, 960)]
        r = analyze_notes(notes, ppq=PPQ, bar_ticks=BAR)
        self.assertEqual(r["overlaps"]["count"], 1)

    def test_different_keys_no_overlap(self):
        notes = [note(60, 0, 960), note(61, 480, 960)]
        r = analyze_notes(notes, ppq=PPQ, bar_ticks=BAR)
        self.assertEqual(r["overlaps"]["count"], 0)


class TestKey(unittest.TestCase):
    def test_explicit_key_out_of_scale(self):
        notes = [note(60, 0, 100), note(62, 240, 100), note(67, 480, 100), note(66, 720, 100)]
        r = analyze_notes(notes, ppq=PPQ, bar_ticks=BAR, key="C major")
        self.assertTrue(r["out_of_scale"]["known"])
        self.assertIn(66, r["out_of_scale"]["keys"])
        self.assertIn("key_assumed", r)

    def test_hypothesis_only_when_no_key(self):
        notes = [note(k, i * 240, 100) for i, k in enumerate([60, 62, 64, 65, 67, 69, 71, 72] * 3)]
        r = analyze_notes(notes, ppq=PPQ, bar_ticks=BAR)
        self.assertIn("key_hypothesis", r)
        self.assertLessEqual(r["key_hypothesis"]["confidence"], 1.0)

    def test_insufficient_data_no_hypothesis(self):
        r = analyze_notes([note(60, 0, 100)], ppq=PPQ, bar_ticks=BAR)
        self.assertNotIn("key_hypothesis", r)

    def test_detect_key_hypothesis_direct(self):
        self.assertIsNone(detect_key_hypothesis([note(60, 0, 1), note(61, 1, 1)]))


if __name__ == "__main__":
    unittest.main()
