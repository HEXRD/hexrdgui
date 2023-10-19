Find orientations and Fit Grains
================================


Notable differences compared to the CLI
=======================================

Hexrdgui gives almost the exact same answer as the CLI for the single
detector GE example we are working with. Find orientations seems to
give the exact same answer for most cases. Fitting the grains has
two notable differences:

1. The GUI is currently automatically converting tensor U to scalar U
   for materials. This results in different values for the structure
   factor, which results in us picking slightly different hkls
   to use for the grain fitting, when we choose the hkls to use
   based upon some structure factor cutoff. This is being tracked in
   issue hexrd/hexrdgui#513.

2. If the Euler angle convention is set to anything other than None,
   some precision gets lost in the tilt angles of the detector. This
   is because the GUI will convert the tilt angles to match the tilt
   convention specified in the GUI, and then when it creates an
   instrument object, it converts the tilt angles back to the None
   convention. This conversion from None to a convention and back to
   None results in a difference at about 12 sig figs in the tilt angles.
   This is a very small difference, but it results in the fit grains
   results being different at about 4 decimal places.

If these two things are taken into account, the GUI gives the exact
same answer as the CLI for fit grains.
