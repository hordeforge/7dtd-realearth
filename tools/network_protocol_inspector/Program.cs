using Mono.Cecil;
using Mono.Cecil.Cil;
var asm=AssemblyDefinition.ReadAssembly(args[0]);
var all=new List<TypeDefinition>();
void Walk(TypeDefinition t){all.Add(t);foreach(var n in t.NestedTypes)Walk(n);}
foreach(var ty in asm.MainModule.Types) Walk(ty);
var t=all.First(x=>x.Name=="NetConnectionSimple");
foreach(var m in t.Methods.Where(m=>m.Name.Contains("Write")||m.Name.Contains("Send")||m.Name.Contains("Compress")||m.Name.Contains("Reader")||m.Name.Contains("Append"))){
  Console.WriteLine("\n## "+m.Name);
  if(m.Body==null) continue;
  int n=0;
  foreach(var i in m.Body.Instructions){
    if(i.Operand is string || (i.Operand is MethodReference mr && (mr.Name.Contains("Compress")||mr.Name.Contains("Write")||mr.Name.Contains("Deflate")||mr.Name.Contains("Copy")||mr.Name.Contains("Read")))
       || (i.Operand is FieldReference fr && fr.Name.Contains("compress"))){
      Console.WriteLine("  "+i.OpCode.Name+" "+i.Operand);
      if(++n>40) break;
    }
  }
}
// NetPackage get_Compress
var np=all.First(x=>x.Name=="NetPackage");
foreach(var m in np.Methods.Where(m=>m.Name.Contains("Compress")||m.Name=="get_Compress")){
  Console.WriteLine("NP."+m.Name);
  if(m.Body!=null) foreach(var i in m.Body.Instructions) Console.WriteLine("  "+i);
}
// PackageIds get_Compress / FlushQueue
var pi=all.First(x=>x.Name=="NetPackagePackageIds");
foreach(var m in pi.Methods.Where(m=>m.Name.Contains("Compress")||m.Name.Contains("Channel")||m.Name.Contains("Flush")||m.Name.Contains("Reliable"))){
  Console.WriteLine("PI."+m.Name);
  if(m.Body!=null) foreach(var i in m.Body.Instructions) Console.WriteLine("  "+i);
}
