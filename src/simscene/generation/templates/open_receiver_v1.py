"""Five separate walls with a visible, unobstructed upward opening."""


def build(s3d,p):
    s3d.empty_scene();s3d.units('m')
    w,d,h,t,f=(p[k] for k in ('interior_width_m','interior_depth_m','interior_height_m','wall_thickness_m','floor_thickness_m'))
    floor=s3d.at(s3d.box('floor',w+2*t,d+2*t,f),z=-f)
    left=s3d.at(s3d.box('left',t,d+2*t,h),x=-(w+t)/2)
    right=s3d.at(s3d.box('right',t,d+2*t,h),x=(w+t)/2)
    back=s3d.at(s3d.box('back',w,t,h),y=(d+t)/2)
    front=s3d.at(s3d.box('front',w,t,h),y=-(d+t)/2)
    for wall in (floor,left,right,back,front):
        s3d.material(wall,'painted_metal',color='#26798c',roughness=.5)
    return s3d.assembly('open_receiver',floor,left,right,back,front)
