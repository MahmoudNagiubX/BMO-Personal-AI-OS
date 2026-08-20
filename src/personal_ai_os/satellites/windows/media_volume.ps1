[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Get', 'Set')]
    [string]$Action,
    [ValidateRange(0, 100)]
    [int]$Value = 0
)

$ErrorActionPreference = 'Stop'
$source = @'
using System;
using System.Runtime.InteropServices;

namespace BmoPhase09Audio {
    public enum EDataFlow { eRender, eCapture, eAll }
    public enum ERole { eConsole, eMultimedia, eCommunications }

    [ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
    public class MMDeviceEnumeratorComObject { }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("A95664D2-9614-4F35-A746-DE8DB63617E6")]
    public interface IMMDeviceEnumerator {
        int EnumAudioEndpoints(EDataFlow dataFlow, uint stateMask, out IntPtr devices);
        int GetDefaultAudioEndpoint(EDataFlow dataFlow, ERole role, out IMMDevice endpoint);
    }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("D666063F-1587-4E43-81F1-B948E807363F")]
    public interface IMMDevice {
        int Activate(ref Guid interfaceId, uint classContext, IntPtr activationParams, [MarshalAs(UnmanagedType.IUnknown)] out object endpointVolume);
    }

    [ComImport, InterfaceType(ComInterfaceType.InterfaceIsIUnknown), Guid("5CDF2C82-841E-4546-9722-0CF74078229A")]
    public interface IAudioEndpointVolume {
        int RegisterControlChangeNotify(IntPtr notify);
        int UnregisterControlChangeNotify(IntPtr notify);
        int GetChannelCount(out uint count);
        int SetMasterVolumeLevel(float levelDb, Guid eventContext);
        int SetMasterVolumeLevelScalar(float level, Guid eventContext);
        int GetMasterVolumeLevel(out float levelDb);
        int GetMasterVolumeLevelScalar(out float level);
    }

    public static class EndpointVolume {
        private static IAudioEndpointVolume Open() {
            var enumerator = (IMMDeviceEnumerator)(new MMDeviceEnumeratorComObject());
            IMMDevice device;
            Marshal.ThrowExceptionForHR(enumerator.GetDefaultAudioEndpoint(EDataFlow.eRender, ERole.eMultimedia, out device));
            Guid id = typeof(IAudioEndpointVolume).GUID;
            object endpoint;
            Marshal.ThrowExceptionForHR(device.Activate(ref id, 23, IntPtr.Zero, out endpoint));
            return (IAudioEndpointVolume)endpoint;
        }

        public static int Get() {
            float scalar;
            Marshal.ThrowExceptionForHR(Open().GetMasterVolumeLevelScalar(out scalar));
            return (int)Math.Round(scalar * 100.0f, MidpointRounding.AwayFromZero);
        }

        public static int Set(int value) {
            Marshal.ThrowExceptionForHR(Open().SetMasterVolumeLevelScalar(value / 100.0f, Guid.Empty));
            return Get();
        }
    }
}
'@

Add-Type -TypeDefinition $source -Language CSharp
if ($Action -eq 'Set') {
    [BmoPhase09Audio.EndpointVolume]::Set($Value)
} else {
    [BmoPhase09Audio.EndpointVolume]::Get()
}
