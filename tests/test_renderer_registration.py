import unittest

from simscene.worker import render_settings as render


PROFILE = {'renderer': 'RaytracedLighting', 'anti_aliasing': 'dlss_quality',
           'depth_of_field': False, 'motion_blur': False, 'exposure_ev': 0.0}
DOF = '/rtx/post/dof/enabled'


class Settings:
    def __init__(self):
        self.values = {key: 0 for key in render.WATCH}
        self.writes = []

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value):
        self.writes.append((key, value))
        self.values[key] = value


class RendererRegistrationTests(unittest.TestCase):
    def test_delayed_native_registration_is_awaited_without_partial_writes(self):
        settings = Settings()
        del settings.values[DOF]
        del settings.values['/rtx/post/tonemap/filmIso']
        updates = []

        def update():
            self.assertEqual(settings.writes, [])
            updates.append(1)
            if len(updates) == 1:
                settings.values[DOF] = False
            if len(updates) == 3:
                settings.values['/rtx/post/tonemap/filmIso'] = 100.0

        result = render.configure(settings, PROFILE, update=update, max_updates=5)
        self.assertEqual(len(updates), 3)
        self.assertEqual(result['registration']['updates'], 3)
        self.assertTrue(result['registration']['all_requested_options_registered'])
        self.assertFalse(result['registration']['created_missing_options'])
        self.assertEqual(settings.values[DOF], False)

    def test_unsupported_option_remains_failure_at_exact_update_bound(self):
        settings = Settings()
        del settings.values[DOF]
        updates = []
        with self.assertRaisesRegex(RuntimeError, 'unavailable after 2 updates'):
            render.configure(settings, PROFILE, update=lambda: updates.append(1), max_updates=2)
        self.assertEqual(len(updates), 2)
        self.assertEqual(settings.writes, [])
        self.assertNotIn(DOF, settings.values)

    def test_missing_option_without_update_callback_fails_without_writes(self):
        settings = Settings()
        del settings.values[DOF]
        with self.assertRaisesRegex(RuntimeError, 'unavailable after 0 updates'):
            render.configure(settings, PROFILE)
        self.assertEqual(settings.writes, [])

    def test_already_registered_false_and_zero_values_do_not_wait(self):
        settings = Settings()
        result = render.configure(settings, PROFILE,
                                  update=lambda: self.fail('registered settings need no update'))
        self.assertEqual(result['registration']['updates'], 0)
        self.assertEqual(result['registration']['initial_missing_options'], [])
        render.check(settings, result['expected'])

    def test_unrequested_dlss_setting_does_not_block_taa(self):
        settings = Settings()
        del settings.values['/rtx/post/dlss/execMode']
        result = render.configure(settings, {**PROFILE, 'anti_aliasing': 'taa'},
                                  update=lambda: self.fail('unrequested option must not block'))
        self.assertNotIn('/rtx/post/dlss/execMode', result['expected'])

    def test_backend_override_still_fails_readback(self):
        class Overridden(Settings):
            def set(self, key, value):
                super().set(key, value)
                if key == DOF:
                    self.values[key] = True

        with self.assertRaisesRegex(RuntimeError, 'renderer setting overridden'):
            render.configure(Overridden(), PROFILE)

    def test_no_explicit_profile_preserves_existing_no_op(self):
        settings = Settings()
        result = render.configure(settings, None,
                                  update=lambda: self.fail('no opt-in profile must not update'))
        self.assertIsNone(result['requested'])
        self.assertEqual(result['before'], result['after_stage'])
        self.assertEqual(settings.writes, [])

    def test_invalid_update_bounds_are_rejected(self):
        for value in (-1, True, 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                render.wait_for_options(Settings(), {DOF: False}, max_updates=value)


if __name__ == '__main__':
    unittest.main()
