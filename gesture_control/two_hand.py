"""Optional pair arbitration. No OS input and no frame-local ID ownership."""
from math import dist, isfinite, log
from .pinch import pinch_ratio
from .pointer import palm_geometry


class TwoHandZoom:
    def __init__(self, settings):
        self.settings=settings
        self.reset()

    def reset(self):
        self.secondary=None
        self.phase='IDLE'
        self.since=None
        self.last_distance=None
        self.remainder=0.

    def choose(self, primary, hands):
        others=[h for h in hands if h.hand_id!=primary.hand_id and
                h.handedness in ('Left','Right') and h.handedness!=primary.handedness and
                (h.handedness_score or 0)>=self.settings.hand_side_min_score and
                len(h.landmarks)==21 and all(isfinite(v) for p in h.landmarks for v in p)]
        if len(others)!=1:
            self.secondary=None
            return None
        hand=others[0]
        center,size=palm_geometry(hand)
        primary_center,_=palm_geometry(primary)
        if size<self.settings.hand_min_size or dist(center,primary_center)<self.settings.zoom_min_separation:
            self.secondary=None
            return None
        if self.secondary is not None and dist(center,self.secondary)>self.settings.hand_match_distance:
            self.secondary=None
            return None
        self.secondary=center
        return hand

    def visible_hand(self, primary, hands):
        """The indicator need not wait for the stricter Zoom side confidence."""
        candidates=[]
        primary_center,_=palm_geometry(primary)
        for hand in hands:
            if hand.hand_id==primary.hand_id:
                continue
            geometry=palm_geometry(hand)
            if geometry is not None:
                center,size=geometry
                if size>=self.settings.hand_min_size and dist(center,primary_center)>=self.settings.zoom_min_separation:
                    candidates.append(hand)
        return candidates[0] if len(candidates)==1 else None

    def update(self, primary, secondary, timestamp, width, height, owned):
        """Return exclusive ownership and a bounded Ctrl-wheel packet."""
        if owned:
            self.phase='IDLE'
            self.since=None
            return False,0
        a=pinch_ratio(primary,width,height)
        b=pinch_ratio(secondary,width,height) if secondary else None
        opened=a is not None and a>=self.settings.pinch_off_ratio
        if self.phase=='EXIT':
            if opened:
                self.phase='IDLE'
                self.since=None
            return True,0
        if self.phase=='ZOOM':
            if a is None or b is None or a>=self.settings.pinch_off_ratio or b>=self.settings.pinch_off_ratio:
                self.phase='EXIT'
                return True,0
            separation=dist(palm_geometry(primary)[0],palm_geometry(secondary)[0])
            self.remainder += log(separation/self.last_distance)*self.settings.zoom_wheel_gain
            self.last_distance=separation
            units=max(-120,min(120,int(self.remainder/120)*120))
            self.remainder-=units
            return True,units
        both=(a is not None and b is not None and a<=self.settings.pinch_on_ratio and b<=self.settings.pinch_on_ratio)
        if both:
            if self.phase!='ENTER':
                self.phase='ENTER'
                self.since=timestamp
            if timestamp-self.since>=self.settings.zoom_enter_ms/1000:
                self.phase='ZOOM'
                self.last_distance=dist(palm_geometry(primary)[0],palm_geometry(secondary)[0])
                self.remainder=0.
            return True,0
        if self.phase=='ENTER':
            self.phase='EXIT'
            return True,0
        # A lone pinch uses the ordinary click debounce. Waiting here swallowed
        # short primary clicks merely because another open hand was visible.
        # Two pinches can claim Zoom before a mouse button has been acquired.
        self.phase='IDLE'
        self.since=None
        return False,0
