import math

import numpy as np

FULL_CAPACITY_GAL = 21.0

SPAN = 50.0  # tank span (inches)
FULL_CHORD = 58  # full wing chord (inches)
T_RATIO = 0.13  # NACA 23013.5 thickness ratio
MAX_THICK = 7.5  # max thickness (inches)
TILT_DEG = 2.5  # fixed dihedral angle of the tank
CHORD_TILT_DEG = 11  # tilt along the chord for tail-low attitude
DEBUG = False  # set True to print solver diagnostics

FILLER_OFFSET = 2.5  # inches from outboard end
FILLER_X_OFFSET = 10.5  # inches forward of the spar


MAX_T_LOC = 0.30
TANK_CHORD = 17  # tank chord length in inches (LE to spar)


# TANK_CHORD = FULL_CHORD * MAX_T_LOC  # tank extends LE -> spar (max thickness)
def airfoil_thickness(x):
    """
    NACA thickness distribution
    x = chord fraction (0-1)
    """

    raw = (
        5
        * T_RATIO
        * (
            0.2969 * np.sqrt(x)
            - 0.1260 * x
            - 0.3516 * x**2
            + 0.2843 * x**3
            - 0.1015 * x**4
        )
    )

    # raw NACA thickness (would normally be t * chord)
    thickness = raw * FULL_CHORD

    # scale so the max thickness equals the real tank thickness
    scale = MAX_THICK / (T_RATIO * FULL_CHORD)

    return thickness * scale


def airfoil_camber(x):
    """
    Camber line for NACA 230-series airfoil.
    x = chord fraction (0–1)
    """

    # 230-series parameters
    p = 0.15  # location of max camber (15% chord)
    k1 = 15.957

    if x < p:
        yc = (k1 / 6) * (x**3 - 3 * p * x**2 + p**2 * (3 - p) * x)
    else:
        yc = (k1 * p**3 / 6) * (1 - x)

    return yc * FULL_CHORD


def section_bounds(x):
    """
    Returns top and bottom surface heights
    """
    yt = airfoil_thickness(x)
    yc = airfoil_camber(x)

    # apply camber line
    top = yc + yt
    bottom = yc - yt

    return top, bottom


def calculate_full_volume():

    NX = 200

    x_vals = np.linspace(0, 1.0, NX)

    dx = TANK_CHORD / NX

    volume = 0.0

    for x in x_vals:

        x_full = x * MAX_T_LOC

        top, bottom = section_bounds(x_full)
        thickness = top - bottom

        volume += thickness * dx * SPAN

    return volume


def calculate_fuel(height_at_filler, angle=TILT_DEG, pitch_angle=CHORD_TILT_DEG):

    tilt = math.radians(angle)
    tilt_chord = math.radians(pitch_angle)

    NX = 200
    NY = 200

    x_vals = np.linspace(0, 1.0, NX)
    y_vals = np.linspace(0, SPAN, NY)

    dx = TANK_CHORD / NX
    dy = SPAN / NY

    volume = 0.0

    filler_y = SPAN - FILLER_OFFSET

    if DEBUG:
        print("DEBUG: filler_y position (inboard distance):", filler_y)
        print("DEBUG: tilt radians:", tilt)

    for x in x_vals:

        # map tank coordinate to full-airfoil coordinate
        x_full = x * MAX_T_LOC

        top, bottom = section_bounds(x_full)

        # ensure fuel surface is relative to tank bottom at filler and cannot exceed tank top
        # local tank bottom at this x position
        fuel_surface = min(bottom + height_at_filler, top)

        for y in y_vals:

            # tank geometry tilt relative to the fuel surface
            # spanwise tilt + chord-wise tilt along x
            # chord-wise tilt: leading edge lower than spar, reference from spar
            delta_chord = math.tan(tilt_chord) * (
                (TANK_CHORD - FILLER_X_OFFSET) - x * TANK_CHORD
            )

            delta_span = math.tan(tilt) * (y - filler_y)  # spanwise dihedral
            delta = delta_span + delta_chord

            # shift the tank section vertically due to tilt
            local_top = top + delta
            local_bottom = bottom + delta

            # fuel surface stays level in gravity reference frame
            fuel_top = min(fuel_surface, local_top)
            fuel_bottom = local_bottom

            if fuel_top > fuel_bottom:

                h = fuel_top - fuel_bottom

                volume += h * dx * dy

    # scale to actual tank capacity
    full_volume = calculate_full_volume()

    if DEBUG:
        print("DEBUG: computed raw volume:", volume)
        print("DEBUG: computed full tank volume:", full_volume)

    gallons = volume / full_volume * FULL_CAPACITY_GAL

    if DEBUG:
        print("DEBUG: scaled gallons:", gallons)

    # calculate fuel height at inboard-most edge
    inboard_y = 0.0  # inboard-most span position

    # map to full-airfoil x coordinate
    x_full_inboard = 0.0 * MAX_T_LOC
    top_inboard, bottom_inboard = section_bounds(x_full_inboard)

    # compute vertical drop from filler to inboard edge due to tilt
    delta_h = math.tan(math.radians(angle)) * (
        (SPAN - FILLER_OFFSET) - inboard_y
    ) + math.tan(math.radians(pitch_angle)) * ((TANK_CHORD - FILLER_X_OFFSET) - 0)

    # fuel height at inboard edge = filler height plus vertical rise at inboard
    fuel_height_inboard = height_at_filler + delta_h

    # clamp to maximum tank thickness
    if fuel_height_inboard > MAX_THICK:
        fuel_height_inboard = MAX_THICK

    return gallons, fuel_height_inboard
