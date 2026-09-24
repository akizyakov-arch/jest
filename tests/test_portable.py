from pathlib import Path
from unittest import TestCase
from gesture_control.portable import arguments


class PortableTests(TestCase):
    def test_default_gui_and_data_beside_executable(self):
        home=Path('D:/Other folder/Приложение')
        self.assertEqual(arguments([],home),['--gui','--config',str(home/'settings.user.json'),
                                            '--log-dir',str(home/'logs')])

    def test_explicit_modes_and_paths_are_preserved(self):
        args=arguments(['--demo','--config=custom.json','--log-dir','custom-logs'],Path('other'))
        self.assertEqual(args,['--demo','--config=custom.json','--log-dir','custom-logs'])
