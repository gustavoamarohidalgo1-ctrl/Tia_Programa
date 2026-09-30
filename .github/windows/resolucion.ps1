# Cambia la resolución de la pantalla de la máquina de pruebas (las de GitHub arrancan en 1024x768).
param([int]$Ancho = 1920, [int]$Alto = 1080)
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class Pantalla {
  [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Ansi)]
  public struct DEVMODE {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
    public short dmSpecVersion; public short dmDriverVersion; public short dmSize; public short dmDriverExtra;
    public int dmFields; public int dmPositionX; public int dmPositionY; public int dmDisplayOrientation;
    public int dmDisplayFixedOutput; public short dmColor; public short dmDuplex; public short dmYResolution;
    public short dmTTOption; public short dmCollate;
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
    public short dmLogPixels; public int dmBitsPerPel; public int dmPelsWidth; public int dmPelsHeight;
    public int dmDisplayFlags; public int dmDisplayFrequency; public int dmICMMethod; public int dmICMIntent;
    public int dmMediaType; public int dmDitherType; public int dmReserved1; public int dmReserved2;
    public int dmPanningWidth; public int dmPanningHeight;
  }
  [DllImport("user32.dll", CharSet = CharSet.Ansi)] public static extern int EnumDisplaySettings(string dispositivo, int modo, ref DEVMODE dm);
  [DllImport("user32.dll", CharSet = CharSet.Ansi)] public static extern int ChangeDisplaySettings(ref DEVMODE dm, int opciones);
  public static int Cambiar(int ancho, int alto) {
    DEVMODE dm = new DEVMODE();
    dm.dmSize = (short)Marshal.SizeOf(typeof(DEVMODE));
    EnumDisplaySettings(null, -1, ref dm);
    dm.dmPelsWidth = ancho; dm.dmPelsHeight = alto; dm.dmFields = 0x80000 | 0x100000;
    return ChangeDisplaySettings(ref dm, 0);
  }
}
'@
$codigo = [Pantalla]::Cambiar($Ancho, $Alto)
Add-Type -AssemblyName System.Windows.Forms
$b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
Write-Host "Cambio de resolución a ${Ancho}x${Alto}: código $codigo; pantalla ahora $($b.Width)x$($b.Height)"
exit ([int]($b.Width -ne $Ancho -or $b.Height -ne $Alto))
