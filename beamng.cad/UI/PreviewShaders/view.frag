#version 430 core
in float shade;
uniform vec4 color;
out vec4 outputColor;
void main(){outputColor=vec4(color.rgb*shade,color.a);}
