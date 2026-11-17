# The Sun and the Moon

NOCS can point at the Sun or the Moon, centre it in the main camera and follow it at
its own rate. Plate solving does not work near them (their light drowns the stars), so
NOCS finds them by their brightness instead.

## Safety first: the Sun

**Never look at the Sun through a telescope, a finder or a camera's viewfinder.** It
blinds at once and for good.

- Point at the Sun only with a **certified solar filter** (ISO 12312-2 film or glass,
  or a solar telescope) that covers the **whole front** of the main telescope. Never
  use a filter that screws into the eyepiece end.
- **Cap or filter the finder and the guide scope** too. Unfiltered sunlight burns a
  camera's sensor and filters within seconds, and can set things alight.
- Keep everyone away from the eyepiece while the telescope moves near the Sun.

NOCS asks you to read this warning before it points within 20° of the Sun while the
Sun is up, the first time each day (at midnight at the site it asks again, and after
NOCS restarts). Finding the Sun stops PHD2, whose guide camera would see the Sun too.

## Finding the Sun or the Moon

Open the mount (Rig → the mount, or the mount button in Explore) and, under **Sun and
Moon**, tap **Find the Moon** or **Find the Sun**. NOCS then:

1. tracks it at the lunar or solar rate, when the mount offers one (the next go to
   elsewhere goes back to the rate the mount had before);
2. points where it should be and takes short frames (0.1 s, binned), looking further
   around in a spiral, up to the **search radius**, until a frame shows its disc;
3. moves the mount a little east and north to learn how the camera sits;
4. centres the disc by its edge (a crescent too), within 2′;
5. syncs the mount there, so go to works better afterwards.

The frames show in Explore as it goes. The finder needs the telescope's focal length in
the profile, and a field of view wider than the disc (about 0.6°).

By day, before a polar alignment, the mount can point several degrees off, and a wide
search takes many frames. It is quicker to bring the body near yourself: stop the
finder, move the mount with the arrows (for the Sun, until the tube's shadow is as
small as it gets; never by looking through the finder), switch on **Search from
here** and start it again.

By day, the Moon near the Sun is searched only away from the Sun until you read the
Sun's warning: places within 20° of it are skipped.

Something brighter in the frame (a planet in a wide field at night, a lit building)
can fool it, and an eclipse or a Moon a day or two from new is not handled.
