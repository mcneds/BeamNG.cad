#version 430 core
layout(std430,binding=0) readonly buffer Source { vec4 points[]; };
layout(std430,binding=3) readonly buffer Faces { uint faces[]; };
layout(std430,binding=5) readonly buffer Lines { vec4 lines[]; };
uniform int mode,n;
uniform vec3 low;
uniform float cell,yaw,pitch,distance,aspect;
out float shade;
const ivec2 corners[6]=ivec2[6](ivec2(0,0),ivec2(1,0),ivec2(1,1),ivec2(0,0),ivec2(1,1),ivec2(0,1));
void main() {
    vec3 p;
    if(mode==0) {p=points[gl_VertexID].xyz;shade=.8;}
    else if(mode==2) {p=lines[gl_VertexID].xyz;shade=1;}
    else {
        uint key=faces[gl_VertexID/6];uint id=key/6u;int face=int(key%6u);
        ivec3 q=ivec3(id%uint(n),(id/uint(n))%uint(n),id/uint(n*n));
        int axis=face/2;ivec2 corner=corners[gl_VertexID%6];
        p=low+vec3(q)*cell;p[axis]+=float(face%2)*cell;
        p[(axis+1)%3]+=float(corner.x)*cell;p[(axis+2)%3]+=float(corner.y)*cell;
        shade=.6+.15*float(axis);
    }
    // Stable centred preview coordinates, Z-up. Final output keeps CAD origin.
    vec3 direction=vec3(cos(pitch)*cos(yaw),cos(pitch)*sin(yaw),sin(pitch));
    vec3 right=normalize(cross(vec3(0,0,1),direction));vec3 up=cross(direction,right);
    float z=distance-dot(p,direction);
    gl_Position=vec4(dot(p,right)*2.41421356/aspect,dot(p,up)*2.41421356,
        (100.001/99.999)*z-(.2/99.999),z);
}
