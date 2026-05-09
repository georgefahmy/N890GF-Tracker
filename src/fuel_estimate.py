import math

import matplotlib.pyplot as plt
import numpy as np

# ---------------------------
# Tank Parameters
# ---------------------------

FULL_CAPACITY_GAL = 21.0

SPAN = 50.0  # tank span (inches)
FULL_CHORD = 58  # full wing chord (inches)
T_RATIO = 0.135  # NACA 23013.5 thickness ratio
MAX_THICK = 7.5  # max thickness (inches)
TILT_DEG = 3.3  # fixed dihedral angle of the tank
CHORD_TILT_DEG = 11  # tilt along the chord for tail-low attitude
DEBUG = False  # set True to print solver diagnostics

FILLER_OFFSET = 2.5  # inches from outboard end
FILLER_X_OFFSET = 10.5  # inches forward of the spar

MAX_T_LOC = 0.30
TANK_CHORD = 17  # tank chord length in inches (LE to spar)
# TANK_CHORD = FULL_CHORD * MAX_T_LOC  # tank extends LE -> spar (max thickness)


# ---------------------------
# NACA Thickness Function
# ---------------------------


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


# ---------------------------
# Cross-section definition
# Only LE to max thickness (~30% chord)
# ---------------------------


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


# ---------------------------
# Fuel volume solver
# ---------------------------


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


# ---------------------------
# Calculate height at filler hole from inboard height
# ---------------------------


def filler_height_from_inboard(inboard_height, angle=TILT_DEG):
    """
    Calculate the fuel height at the filler hole given the inboard-most fuel height.
    """
    # tank parameters
    tilt = math.radians(angle)
    inboard_y = 0.0  # inboard-most position
    filler_y = SPAN - FILLER_OFFSET  # outboard filler position

    # vertical difference due to tilt
    delta_h = math.tan(tilt) * (filler_y - inboard_y)

    # height at filler = inboard height minus the vertical drop
    height_filler = inboard_height - delta_h

    if DEBUG:
        print(f"DEBUG: inboard height: {inboard_height}")
        print(f"DEBUG: vertical drop to filler (delta_h): {delta_h}")
        print(f"DEBUG: calculated filler height: {height_filler}")

    return height_filler


def plot_airfoil_with_tank(height_at_filler, pitch_angle=CHORD_TILT_DEG):
    """
    Plot the full airfoil cross-section and highlight the portion used as the fuel tank.
    The tank region is from the leading edge to TANK_CHORD.
    """

    N = 400

    x_frac = np.linspace(0, 1.0, N)

    x_coords = []
    top_surface = []
    bottom_surface = []
    fuel_top_surface = []
    fuel_bottom_surface = []

    for xf in x_frac:

        x = xf * FULL_CHORD

        # use the same geometry routine as the fuel solver
        top, bottom = section_bounds(xf)

        # fuel surface relative to local tank bottom at filler location
        fuel_surface = min(bottom + height_at_filler, top)

        x_coords.append(x)
        top_surface.append(top)
        bottom_surface.append(bottom)

        fuel_top_surface.append(fuel_surface)
        fuel_bottom_surface.append(bottom)

    x_coords = np.array(x_coords)
    top_surface = np.array(top_surface)
    bottom_surface = np.array(bottom_surface)
    fuel_top_surface = np.array(fuel_top_surface)
    fuel_bottom_surface = np.array(fuel_bottom_surface)

    # negative sign so positive CHORD_TILT_DEG produces a nose-up rotation
    theta = -math.radians(pitch_angle)

    x_top_rot = x_coords * np.cos(theta) - top_surface * np.sin(theta)
    y_top_rot = x_coords * np.sin(theta) + top_surface * np.cos(theta)

    x_bot_rot = x_coords * np.cos(theta) - bottom_surface * np.sin(theta)
    y_bot_rot = x_coords * np.sin(theta) + bottom_surface * np.cos(theta)

    # determine fuel level in the rotated frame so the surface stays horizontal
    filler_x = TANK_CHORD - FILLER_X_OFFSET
    filler_bottom = np.interp(filler_x, x_coords, bottom_surface)

    filler_x_rot = filler_x * np.cos(theta) - filler_bottom * np.sin(theta)
    filler_y_rot = filler_x * np.sin(theta) + filler_bottom * np.cos(theta)

    fuel_level = filler_y_rot + height_at_filler

    plt.figure()

    # full airfoil outline (rotated)
    plt.plot(x_top_rot, y_top_rot)
    plt.plot(x_bot_rot, y_bot_rot)

    # highlight tank region (LE to spar, rotated)
    tank_mask = x_coords <= TANK_CHORD

    # fuel occupies space between tank bottom and horizontal fuel level
    fuel_top = np.minimum(fuel_level, y_top_rot)

    valid = tank_mask & (fuel_top > y_bot_rot)

    # build polygon so the right edge follows the spar tilt
    poly_x = list(x_bot_rot[valid])
    poly_y = list(y_bot_rot[valid])

    # interpolate along spar based on fuel level
    spar_bottom = np.interp(TANK_CHORD, x_coords, bottom_surface)
    spar_top = np.interp(TANK_CHORD, x_coords, top_surface)

    frac = (fuel_level - (TANK_CHORD * np.sin(theta) + spar_bottom * np.cos(theta))) / (
        (TANK_CHORD * np.sin(theta) + spar_top * np.cos(theta))
        - (TANK_CHORD * np.sin(theta) + spar_bottom * np.cos(theta))
    )
    frac = np.clip(frac, 0.0, 1.0)

    # compute interpolated y along spar (linear along spar line)
    spar_y_interp = (
        TANK_CHORD * np.sin(theta) + spar_bottom * np.cos(theta)
    ) + frac * (
        (TANK_CHORD * np.sin(theta) + spar_top * np.cos(theta))
        - (TANK_CHORD * np.sin(theta) + spar_bottom * np.cos(theta))
    )
    spar_x_interp = (
        TANK_CHORD * np.cos(theta) - spar_bottom * np.sin(theta)
    ) + frac * (
        (TANK_CHORD * np.cos(theta) - spar_top * np.sin(theta))
        - (TANK_CHORD * np.cos(theta) - spar_bottom * np.sin(theta))
    )

    poly_x += [spar_x_interp]
    poly_y += [spar_y_interp]

    # add top surface back toward leading edge
    poly_x += list(x_top_rot[valid][::-1])
    poly_y += list(fuel_top[valid][::-1])

    plt.fill(poly_x, poly_y, alpha=0.5, label="Fuel Volume")
    plt.plot(
        [
            TANK_CHORD * np.cos(theta)
            - np.interp(TANK_CHORD, x_coords, bottom_surface) * np.sin(theta),
            TANK_CHORD * np.cos(theta)
            - np.interp(TANK_CHORD, x_coords, top_surface) * np.sin(theta),
        ],
        [
            TANK_CHORD * np.sin(theta)
            + np.interp(TANK_CHORD, x_coords, bottom_surface) * np.cos(theta),
            TANK_CHORD * np.sin(theta)
            + np.interp(TANK_CHORD, x_coords, top_surface) * np.cos(theta),
        ],
        linestyle="--",
        label="Tank",
    )

    # filler location
    filler_x = TANK_CHORD - FILLER_X_OFFSET
    filler_y = np.interp(filler_x, x_coords, top_surface)

    filler_x_rot = filler_x * np.cos(theta) - filler_y * np.sin(theta)
    filler_y_rot = filler_x * np.sin(theta) + filler_y * np.cos(theta)

    plt.scatter([filler_x_rot], [filler_y_rot], label="Filler Hole")

    plt.xlabel("Chord Position (inches)")
    plt.ylabel("Airfoil Thickness (inches)")
    plt.title("Airfoil Cross Section with Fuel Tank Region")
    plt.axis("equal")
    plt.legend()
    return plt


def plot_3d_wing(
    airfoil_func,
    height1=0,
    height2=0,
    span=SPAN,
    chord=TANK_CHORD,
    num_chord_points=100,
    num_span_points=50,
    angle=TILT_DEG,
    pitch_angle=CHORD_TILT_DEG,
):
    """
    Plots a 3D wing using a specified airfoil function.

    Parameters:
    - airfoil_func(x): function returning (top, bottom) for a chord fraction x (0–1)
    - span: wing span in inches
    - chord: chord length in inches
    - num_chord_points: resolution along chord
    - num_span_points: resolution along span
    """

    x_frac = np.linspace(0, 1.0, num_chord_points)
    y_span = np.linspace(0, span, num_span_points)

    X, Y = np.meshgrid(x_frac * chord, y_span)
    Z_top = np.zeros_like(X)
    Z_bottom = np.zeros_like(X)

    for i in range(num_span_points):  # spanwise
        for j in range(num_chord_points):  # chordwise
            xf = X[i, j] / chord  # normalized chord fraction
            top, bottom = airfoil_func(xf)

            Z_top[i, j] = top
            Z_bottom[i, j] = bottom

    fig = plt.figure(figsize=(14, 8))
    ax = fig.add_subplot(121, projection="3d")
    ax2 = fig.add_subplot(122, projection="3d")

    # Apply both chordwise tilt and spanwise tilt to the wing surfaces
    tilt_span = math.radians(angle)
    theta_chord = -math.radians(pitch_angle)  # negative for nose-up rotation

    # filler_y for reference (spanwise position of filler)
    filler_y = SPAN - FILLER_OFFSET

    # rotate wing surfaces with chord and span tilt
    X_rot = X * np.cos(theta_chord) - Z_top * np.sin(theta_chord)
    Z_chord_rot = X * np.sin(theta_chord) + Z_top * np.cos(theta_chord)
    Z_top_rot = Z_chord_rot + np.tan(tilt_span) * (Y - filler_y)

    X_rot_bot = X * np.cos(theta_chord) - Z_bottom * np.sin(theta_chord)
    Z_chord_rot_bot = X * np.sin(theta_chord) + Z_bottom * np.cos(theta_chord)
    Z_bottom_rot = Z_chord_rot_bot + np.tan(tilt_span) * (Y - filler_y)
    Z_bottom_rot2 = Z_chord_rot_bot + np.tan(tilt_span) * (Y - filler_y)

    # spar surface along the span at TANK_CHORD
    # create 2D arrays for the spar surface
    X_spar_2d = np.full((2, len(y_span)), TANK_CHORD)
    Y_spar_2d = np.tile(y_span, (2, 1))

    Z_spar_2d = np.zeros_like(X_spar_2d)

    for i in range(len(y_span)):
        top, bottom = airfoil_func(TANK_CHORD / chord)
        Z_spar_2d[0, i] = bottom
        Z_spar_2d[1, i] = top

    # rotate spar surface using both chordwise and spanwise tilt
    xf_spar = TANK_CHORD / chord
    top_spar, bottom_spar = airfoil_func(xf_spar)
    # rotate top and bottom points using chordwise tilt
    top_spar_rot = TANK_CHORD * np.sin(theta_chord) + top_spar * np.cos(theta_chord)
    bottom_spar_rot = TANK_CHORD * np.sin(theta_chord) + bottom_spar * np.cos(
        theta_chord
    )
    # apply spanwise tilt
    Z_spar_rot_top = np.zeros_like(Y_spar_2d)
    Z_spar_rot_bottom = np.zeros_like(Y_spar_2d)
    Z_spar_rot_top[:, :] = top_spar_rot + np.tan(tilt_span) * (Y_spar_2d - filler_y)
    Z_spar_rot_bottom[:, :] = bottom_spar_rot + np.tan(tilt_span) * (
        Y_spar_2d - filler_y
    )

    # set equal aspect ratio for x, y, z
    max_range = (
        np.array(
            [
                X_rot.max() - X_rot.min(),
                Y.max() - Y.min(),
                Z_top_rot.max() - Z_bottom_rot.min(),
            ]
        ).max()
        / 2.0
    )
    mid_x = (X_rot.max() + X_rot.min()) * 0.5
    mid_y = (Y.max() + Y.min()) * 0.5
    mid_z = (Z_top_rot.max() + Z_bottom_rot.min()) * 0.5
    mid_z2 = (Z_top_rot.max() + Z_bottom_rot2.min()) * 0.5

    ax.set_xlim(mid_x - max_range, mid_x + max_range)
    ax2.set_xlim(mid_x - max_range, mid_x + max_range)
    ax.set_ylim(mid_y - max_range, mid_y + max_range)
    ax2.set_ylim(mid_y - max_range, mid_y + max_range)
    ax.set_zlim(mid_z - max_range, mid_z + max_range)
    ax2.set_zlim(mid_z2 - max_range, mid_z2 + max_range)

    # plot wing surfaces
    ax.plot_surface(X_rot, Y, Z_top_rot, color="gray", alpha=0.3)
    ax2.plot_surface(X_rot, Y, Z_top_rot, color="gray", alpha=0.3)
    ax.plot_surface(X_rot_bot, Y, Z_bottom_rot, color="lightgray", alpha=0.7)
    ax2.plot_surface(X_rot_bot, Y, Z_bottom_rot2, color="lightgray", alpha=0.7)

    # # plot as two surfaces (top and bottom) with alpha=1
    # ax.plot_surface(X_spar_rot_2d, Y_spar_2d, Z_spar_rot_top, color="blue", alpha=1)
    # ax.plot_surface(X_spar_rot_2d, Y_spar_2d, Z_spar_rot_bottom, color="blue", alpha=1)

    # ---------------------------
    # Add fuel surfaces based on height at filler
    # ---------------------------
    # calculate fuel surfaces based on height at filler
    # ---------------------------
    # Flat fuel surface: use bottom surface at filler hole, flat across tank
    # ---------------------------
    # determine bottom surface under filler hole
    filler_x = TANK_CHORD - FILLER_X_OFFSET  # chordwise position of filler
    filler_y_pos = SPAN - FILLER_OFFSET  # spanwise position of filler

    xf_filler = filler_x / chord
    top_filler, bottom_filler = airfoil_func(xf_filler)

    # rotate bottom under filler for chord tilt only (ignore span tilt for fuel surface)
    theta_chord = -math.radians(pitch_angle)  # nose-up
    bottom_filler_rot = filler_x * np.sin(theta_chord) + bottom_filler * np.cos(
        theta_chord
    )

    fuel_surface_height = bottom_filler_rot + height1
    fuel_surface_height2 = bottom_filler_rot + height2

    # assign fuel top surface only forward of spar
    Z_fuel_top = np.where(
        X <= TANK_CHORD,
        np.minimum(fuel_surface_height, Z_top_rot),  # can't exceed wing top
        Z_top_rot,
    )
    Z_fuel_top2 = np.where(
        X <= TANK_CHORD,
        np.minimum(fuel_surface_height2, Z_top_rot),  # can't exceed wing top
        Z_top_rot,
    )

    # ensure fuel surface is never below the wing bottom
    Z_fuel_top = np.maximum(Z_fuel_top, Z_bottom_rot)
    Z_fuel_top2 = np.maximum(Z_fuel_top2, Z_bottom_rot2)
    # Z_fuel_bottom = Z_bottom_rot.copy()

    # Only plot fuel top surface (parallel to gravity) and side surfaces
    Z_fuel_top_clamped = np.minimum(Z_fuel_top, Z_top_rot)
    Z_fuel_top_clamped2 = np.minimum(Z_fuel_top2, Z_top_rot)

    # only select points where X_rot is between 0 and TANK_CHORD
    X_fuel_plot = np.where(X_rot <= TANK_CHORD, X_rot, np.nan)

    # only plot fuel where fuel surface is above the wing bottom
    fuel_mask = Z_fuel_top_clamped > Z_bottom_rot
    fuel_mask2 = Z_fuel_top_clamped2 > Z_bottom_rot2
    X_fuel_masked = np.where(fuel_mask, X_fuel_plot, np.nan)
    X_fuel_masked2 = np.where(fuel_mask2, X_fuel_plot, np.nan)
    Z_fuel_masked = np.where(fuel_mask, Z_fuel_top_clamped, np.nan)
    Z_fuel_masked2 = np.where(fuel_mask2, Z_fuel_top_clamped2, np.nan)

    ax.plot_surface(X_fuel_masked, Y, Z_fuel_masked, color="purple", alpha=0.7)
    ax2.plot_surface(X_fuel_masked2, Y, Z_fuel_masked2, color="purple", alpha=0.7)

    # plot filler hole as black dot on wing top surface height (not fuel surface)
    filler_x_rot = filler_x * np.cos(theta_chord) - bottom_filler * np.sin(theta_chord)
    # Place dot at the lesser of fuel surface or actual wing top at that chordwise location
    # chordwise index closest to filler
    idx_filler = np.argmin(np.abs(X[0, :] - filler_x))

    # wing top at filler location (before rotation)
    top_at_filler = Z_top[0, idx_filler]

    # chord tilt rotation
    theta_chord = -math.radians(pitch_angle)  # nose-up

    # span tilt in radians
    tilt_span = math.radians(angle)

    # chordwise rotated Z
    z_chord_rot = X[0, idx_filler] * np.sin(theta_chord) + top_at_filler * np.cos(
        theta_chord
    )

    # apply spanwise tilt along y relative to filler_y
    filler_z = z_chord_rot + math.tan(tilt_span) * (filler_y_pos - filler_y_pos)
    ax.scatter(
        [filler_x_rot],
        [filler_y_pos],
        [filler_z],
        color="black",
        s=50,
        label="Filler Hole",
    )
    ax2.scatter(
        [filler_x_rot],
        [filler_y_pos],
        [filler_z],
        color="black",
        s=50,
        label="Filler Hole",
    )

    ax.set_xlabel("Chord (inches)")
    ax.set_ylabel("Span (inches)")
    ax.set_zlabel("Height (inches)")
    ax.set_title("3D Wing Planform")
    ax.legend()
    return plt


# ---------------------------
# Example
# ---------------------------

if __name__ == "__main__":

    left = float(input("Input first fuel level: "))
    right = float(input("Input first fuel level: "))

    gallons_1, inboard_height1 = calculate_fuel(left, TILT_DEG, CHORD_TILT_DEG)
    gallons_2, inboard_height2 = calculate_fuel(right, TILT_DEG, CHORD_TILT_DEG)

    print(f"\nEstimated Fuel: {gallons_1 + gallons_2:.2f} gallons")
    print(f"Estimated inboard-most fuel height: {inboard_height1:.2f} inches")
    # plot2d = plot_airfoil_with_tank(height, pitch_angle=pitch_angle)
    plot3d = plot_3d_wing(
        section_bounds,
        span=SPAN,
        height1=left,
        height2=right,
        chord=FULL_CHORD,
        num_chord_points=200,
        num_span_points=10,
        angle=TILT_DEG,
        pitch_angle=CHORD_TILT_DEG,
    )
    plt.show()
