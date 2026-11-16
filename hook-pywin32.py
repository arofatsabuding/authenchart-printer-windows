from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = collect_submodules('win32com') + collect_submodules('win32') + ['win32ui']
datas = collect_data_files('pywin32')