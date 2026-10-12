param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$code=[Reflection.Assembly]::LoadFrom((Join-Path $OutputDirectory 'beamng.cad.dll'))
function New-Record($name){[Activator]::CreateInstance($code.GetType('BeamNG.Cad.Preparation.'+$name),$true)}
function Set-Field($value,$name,$data){$value.GetType().GetField($name).SetValue($value,$data)}
function Get-Field($value,$name){,$value.GetType().GetField($name).GetValue($value)}
$component=New-Record 'ComponentDefinition'
Set-Field $component 'Id' 'coilover'; Set-Field $component 'Name' 'Test shock'
$ids=Get-Field $component 'BodyIds'
foreach($id in @('can','rod','coil')){$ids.Add($id)}
$appearance=New-Record 'CoiloverAppearance';Set-Field $component 'AppearanceCoilover' $appearance
$pieces=Get-Field $appearance 'Pieces'
foreach($pair in @(@('housing','can'),@('shaft','rod'),@('spring','coil'))){
    $piece=New-Record 'CoiloverMeshAssignment';Set-Field $piece 'Kind' $pair[0]
    (Get-Field $piece 'BodyIds').Add($pair[1]);$pieces.Add($piece)
}
$method=$code.GetType('BeamNG.Cad.Preparation.AssociationAssembly').GetMethod('AssignedCoiloverMembers',[Reflection.BindingFlags]'Static,NonPublic')
$members=$method.Invoke($null,@($component))
if($members.Count -ne 3){throw 'Complete partition must produce three moving members'}
foreach($member in $members){if((Get-Field $member 'ComponentId') -ne 'coilover'){throw 'Logical ownership lost'}}
Write-Output 'PASS complete coilover assignments become three members with one logical owner'
$ids.Add('unassigned')
if($null -ne $method.Invoke($null,@($component))){throw 'Incomplete physical ownership must not be guessed'}
Write-Output 'PASS extra physical body requires classification'
[void]$ids.Remove('unassigned')
(Get-Field $pieces[1] 'BodyIds').Add('can')
if($null -ne $method.Invoke($null,@($component))){throw 'Overlapping moving pieces must not be split'}
Write-Output 'PASS overlapping body ownership rejected'
