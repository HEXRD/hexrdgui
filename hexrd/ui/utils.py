# Some general utilities that are used in multiple places


def fix_exclusions(mat):
    # The default is to exclude all hkl's after the 5th one.
    # (See Material._newPdata() for more info)
    # Let's not do this...
    excl = [False] * len(mat.planeData.exclusions)
    mat.planeData.exclusions = excl


def make_new_pdata(mat):
    # This generates new PlaneData for a material
    # It also fixes the exclusions (see fix_exclusions() for details)
    mat._newPdata()
    fix_exclusions(mat)
