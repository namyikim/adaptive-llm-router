"""No provider/Docker calls: explicit normalization must preserve every edit."""
import hashlib
import importlib
import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from adaptive_llm_router.model_diff import extract_complete_diff, ModelDiffError

DIFF = ('diff --git a/tqdm/_tqdm.py b/tqdm/_tqdm.py\n'
        '--- a/tqdm/_tqdm.py\n+++ b/tqdm/_tqdm.py\n'
        '@@ -7,3 +7,4 @@\n context\n-old\n+new\n+extra\n end\n')

class SavedResponseNormalizationTests(unittest.TestCase):
    def normalizer(self):
        name = 'adaptive_llm_router.model_diff_normalization'
        self.assertIsNotNone(importlib.util.find_spec(name),
                             'Explicit assisted track is not implemented yet')
        return importlib.import_module(name).normalize_saved_response

    def test_strict_valid_diff_is_unchanged(self):
        result, audit = self.normalizer()(DIFF, 'tqdm-6')
        self.assertEqual(result, DIFF.encode())
        self.assertTrue(audit['strict_original_accepted'])
        self.assertEqual(audit['count_changes'], [])
        self.assertTrue(audit['body_preserved'])

    def test_assistance_is_explicit_and_does_not_relax_original_parser(self):
        answer = '- Explanation, not code.\n\n```diff\n' + DIFF + '```\n'
        normalize = self.normalizer()
        with self.assertRaises(ValueError):
            normalize(answer, 'tqdm-6')
        result, audit = normalize(answer, 'tqdm-6', allow_count_repair=True)
        self.assertEqual(result, DIFF.encode())
        self.assertFalse(audit['strict_original_accepted'])
        self.assertTrue(audit['envelope_removed'])
        with self.assertRaises(ModelDiffError):
            extract_complete_diff(answer)

    def test_recount_preserves_offsets_and_every_body_byte(self):
        wrong = DIFF.replace('@@ -7,3 +7,4 @@', '@@ -7,2 +7,3 @@')
        answer = '- Explanation.\n```diff\n' + wrong + '```\n'
        digest = hashlib.sha256(answer.encode()).hexdigest()
        result, audit = self.normalizer()(answer, 'tqdm-6', allow_count_repair=True)
        self.assertEqual(result, DIFF.encode())
        self.assertEqual(audit['response_sha256'], digest)
        self.assertEqual(audit['count_changes'][0]['before'], '@@ -7,2 +7,3 @@')
        self.assertEqual(audit['count_changes'][0]['after'], '@@ -7,3 +7,4 @@')
        self.assertEqual(audit['body_sha256_before'], audit['body_sha256_after'])
        self.assertEqual(extract_complete_diff(result.decode()), result)
        self.assertEqual(hashlib.sha256(answer.encode()).hexdigest(), digest)

    def test_rejects_ambiguous_or_unclosed_patch_blocks(self):
        normalize = self.normalizer()
        for raw in ('```diff\n' + DIFF,
                    '```diff\n' + DIFF + '```\n```diff\n' + DIFF + '```',
                    DIFF + '\n```diff\n' + DIFF + '```',
                    '```diff\n' + DIFF + '```\n@@ -1 +1 @@\n-old\n+new'):
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                normalize(raw, 'tqdm-6', allow_count_repair=True)

    def test_rejects_prose_inside_hunk_and_forbidden_paths(self):
        normalize = self.normalizer()
        for raw in (DIFF.replace(' end\n', 'Explanation here\n'),
                    DIFF.replace('tqdm/_tqdm.py', 'tqdm/tests/test.py'),
                    DIFF.replace('tqdm/_tqdm.py', '../outside.py'),
                    DIFF.replace('@@ -7,3 +7,4 @@', '@@ broken'),
                    DIFF + 'GIT binary patch\n',
                    DIFF.replace('@@ -7,3 +7,4 @@', '@@ -0,3 +0,4 @@')):
            with self.subTest(raw=raw[:50]), self.assertRaises(ValueError):
                normalize('```diff\n' + raw + '```', 'tqdm-6', allow_count_repair=True)

    def test_multifile_contents_remain_complete(self):
        first = DIFF.replace('tqdm/_tqdm.py', 'tornado/ioloop.py')
        second = DIFF.replace('tqdm/_tqdm.py', 'tornado/platform/asyncio.py')
        wrong = (first + second).replace('@@ -7,3 +7,4 @@', '@@ -7,2 +7,3 @@')
        patch, audit = self.normalizer()('```diff\n' + wrong + '```',
                                        'tornado-6', allow_count_repair=True)
        self.assertEqual(patch, (first + second).encode())
        self.assertEqual(len(audit['count_changes']), 2)
        self.assertTrue(audit['body_preserved'])

if __name__ == '__main__':
    unittest.main()
