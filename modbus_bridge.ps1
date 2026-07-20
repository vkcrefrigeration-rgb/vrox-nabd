# ================================================================
# VROX — Modbus TCP to JSON Bridge
# Reads Schneider M241 PLC registers and writes to JSON file
# Run: powershell -ExecutionPolicy Bypass -File modbus_bridge.ps1
# ================================================================

param(
    [string]$PLC_IP = "192.168.1.10",
    [int]$PLC_Port = 502,
    [string]$JSON_File = "C:\Users\frost\Desktop\VROX_HMI\plc_data.json",
    [int]$Interval = 1000  # milliseconds
)

# Register definitions (Modbus Holding Registers)
$registers = @(
    @{Name="T_Box";       Addr=0;  Type="Float"; Factor=1.0},
    @{Name="T_Plate";     Addr=2;  Type="Float"; Factor=1.0},
    @{Name="Plate_SOC";   Addr=4;  Type="Float"; Factor=1.0},
    @{Name="T_Target";    Addr=6;  Type="Float"; Factor=1.0},
    @{Name="T_Ambient";   Addr=8;  Type="Float"; Factor=1.0},
    @{Name="V_Bat";       Addr=10; Type="Float"; Factor=1.0},
    @{Name="Bat_SOC";     Addr=12; Type="Float"; Factor=1.0},
    @{Name="Solar_Power"; Addr=14; Type="Float"; Factor=1.0},
    @{Name="State";       Addr=16; Type="Int16"; Factor=1.0},
    @{Name="OffCycle_Min";Addr=18; Type="Float"; Factor=1.0},
    @{Name="OnCycle_Min"; Addr=20; Type="Float"; Factor=1.0},
    @{Name="Fuel_Saved";  Addr=22; Type="Float"; Factor=1.0},
    @{Name="Titan_Prog";  Addr=24; Type="Float"; Factor=1.0},
    @{Name="ErrorCode";   Addr=26; Type="UInt16";Factor=1.0},
    @{Name="Flow_Coil";   Addr=28; Type="Float"; Factor=1.0},
    @{Name="Icing";       Addr=30; Type="Bool";  Factor=1.0},
    @{Name="Engine_Run";  Addr=32; Type="Bool";  Factor=1.0}
)

function Read-ModbusTCP {
    param($ip, $port, $unitId=1, $startAddr=0, $quantity=34)
    
    try {
        $client = New-Object System.Net.Sockets.TcpClient($ip, $port)
        $client.ReceiveTimeout = 3000
        $client.SendTimeout = 3000
        $stream = $client.GetStream()

        # Build Modbus TCP frame: Read Holding Registers (FC=03)
        # [TransactionID:2][Protocol:2][Length:2][UnitID:1][FC:1][StartAddr:2][Quantity:2]
        $transactionId = Get-Random -Maximum 65535
        $frame = New-Object byte[] 12
        $frame[0] = ($transactionId -shr 8) -band 0xFF
        $frame[1] = $transactionId -band 0xFF
        $frame[2] = 0; $frame[3] = 0  # Protocol ID
        $frame[4] = 0; $frame[5] = 6   # Length
        $frame[6] = $unitId            # Unit ID
        $frame[7] = 3                  # Function Code: Read Holding Registers
        $frame[8] = ($startAddr -shr 8) -band 0xFF
        $frame[9] = $startAddr -band 0xFF
        $frame[10] = ($quantity -shr 8) -band 0xFF
        $frame[11] = $quantity -band 0xFF

        $stream.Write($frame, 0, 12)

        # Read response header (7 bytes)
        $header = New-Object byte[] 7
        $stream.Read($header, 0, 7) | Out-Null

        $byteCount = $header[6]
        if ($byteCount -gt 200) {
            $client.Close()
            return $null
        }

        # Read data bytes
        $data = New-Object byte[] $byteCount
        $stream.Read($data, 0, $byteCount) | Out-Null
        $client.Close()

        return $data
    }
    catch {
        return $null
    }
}

function Convert-BytesToValue {
    param($bytes, $offset, $type)
    
    switch($type) {
        "Float" {
            $val = [BitConverter]::ToSingle([byte[]]@($bytes[$offset+1], $bytes[$offset], $bytes[$offset+3], $bytes[$offset+2]), 0)
            return [math]::Round($val, 1)
        }
        "Int16" {
            return ($bytes[$offset] -shl 8) -bor $bytes[$offset+1]
        }
        "UInt16" {
            return ($bytes[$offset] * 256) + $bytes[$offset+1]
        }
        "Bool" {
            return (($bytes[$offset] -shl 8) -bor $bytes[$offset+1]) -ne 0
        }
    }
    return 0
}

Write-Host "=== VROX Modbus Bridge ==="
Write-Host "PLC: $PLC_IP`:$PLC_Port"
Write-Host "Output: $JSON_File"
Write-Host "Interval: $Interval ms"
Write-Host ""

$count = 0
while ($true) {
    $count++
    $raw = Read-ModbusTCP -ip $PLC_IP -port $PLC_Port -startAddr 0 -quantity 34

    $values = @{}
    if ($raw) {
        foreach ($reg in $registers) {
            $values[$reg.Name] = Convert-BytesToValue -bytes $raw -offset ($reg.Addr * 2) -type $reg.Type
        }
        $values["_connected"] = $true
        $values["_timestamp"] = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    } else {
        # PLC not responding — use zeros
        foreach ($reg in $registers) {
            $values[$reg.Name] = 0
        }
        $values["_connected"] = $false
        $values["_timestamp"] = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    }

    $json = ConvertTo-Json -InputObject $values -Compress
    Set-Content -Path $JSON_File -Value $json -Encoding ASCII

    if ($count % 10 -eq 0) {
        $status = if($values["_connected"]){"OK"}else{"NO PLC"}
        Write-Host "[$count] PLC: $status | Box: $($values['T_Box'])'C | Plate: $($values['T_Plate'])'C"
    }

    Start-Sleep -Milliseconds $Interval
}