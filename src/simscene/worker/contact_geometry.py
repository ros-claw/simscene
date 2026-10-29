"""Extract penetration evidence from the contact points PhysX reports."""
import math

def minimum_separation(header,data):
    try:
        offset=header.contact_data_offset;count=header.num_contact_data
        if type(offset) is not int or type(count) is not int or offset<0 or count<0 or offset+count>len(data):return None,True
        if not count:return None,False
        values=[float(data[i].separation) for i in range(offset,offset+count)]
        if not all(math.isfinite(x) for x in values):return None,True
        return min(values),False
    except (AttributeError,TypeError,ValueError,OverflowError):return None,True
