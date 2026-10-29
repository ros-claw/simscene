"""Geometry helpers using world-space metres and wxyz quaternions."""
import math
from .scene import SceneError

def camera_orientation(position, target):
    def norm(v):
        length = math.sqrt(sum(x*x for x in v))
        if length < 1e-9: raise SceneError('camera and target must have different positions')
        return [x / length for x in v]
    def cross(a,b):
        return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
    forward = norm([b-a for a,b in zip(position,target)])
    up = [0,0,1] if abs(forward[2]) < .999 else [0,1,0]
    right = norm(cross(forward, up))
    up = cross(right, forward)
    # USD camera looks down local -Z, with local +Y up.
    m = [[right[i],up[i],-forward[i]] for i in range(3)]
    trace = sum(m[i][i] for i in range(3))
    if trace > 0:
        s = math.sqrt(trace+1)*2
        q = [s/4,(m[2][1]-m[1][2])/s,(m[0][2]-m[2][0])/s,(m[1][0]-m[0][1])/s]
    else:
        i = max(range(3), key=lambda k:m[k][k])
        if i == 0:
            s = math.sqrt(1+m[0][0]-m[1][1]-m[2][2])*2
            q = [(m[2][1]-m[1][2])/s,s/4,(m[0][1]+m[1][0])/s,(m[0][2]+m[2][0])/s]
        elif i == 1:
            s = math.sqrt(1+m[1][1]-m[0][0]-m[2][2])*2
            q = [(m[0][2]-m[2][0])/s,(m[0][1]+m[1][0])/s,s/4,(m[1][2]+m[2][1])/s]
        else:
            s = math.sqrt(1+m[2][2]-m[0][0]-m[1][1])*2
            q = [(m[1][0]-m[0][1])/s,(m[0][2]+m[2][0])/s,(m[1][2]+m[2][1])/s,s/4]
    return norm(q)
