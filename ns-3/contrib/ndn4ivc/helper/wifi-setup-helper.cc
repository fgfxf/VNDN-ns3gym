#include "ns3/wifi-setup-helper.h"
#include "ns3/propagation-environment.h"


namespace ns3 {
namespace ndn {

WifiSetupHelper::WifiSetupHelper ()
{
}

WifiSetupHelper::~WifiSetupHelper ()
{
}

NetDeviceContainer
WifiSetupHelper::ConfigureDevices (NodeContainer &nodes, bool enablePcap)
{
  /** Propagationa = TwoRayGroundPropagationLossModel && ConstantSpeedPropagationDelayModel***
  * 21dBm ~ 75m (radio coverage)
  * 33.8dbm ~ 200m  (radio coverage)
  * 45.6dbm~ 500m  (radio coverage)
  */

  /* Propagation loss models >> implemented:
  - Cost231PropagationLossModel
  - FixedRssLossModel
  - FriisPropagationLossModel
  - ItuR1411LosPropagationLossModel
  - ItuR1411NlosOverRooftopPropagationLossModel
  - JakesPropagationLossModel
  - Kun2600MhzPropagationLossModel
  - LogDistancePropagationLossModel
  - MatrixPropagationLossModel
  - NakagamiPropagationLossModel
  - OkumuraHataPropagationLossModel
  - RandomPropagationLossModel
  - RangePropagationLossModel
  - ThreeLogDistancePropagationLossModel
  - TwoRayGroundPropagationLossModel

  More info: https://coe.northeastern.edu/Research/krclab/crens3-doc/group___attribute_list.html
  
  ns3::TwoRayGroundPropagationLossModel
    Frequency: The carrier frequency (in Hz) at which propagation occurs (default is 5.15 GHz).
    SystemLoss: The system loss
    MinDistance: The distance under which the propagation model refuses to give results (m)
    HeightAboveZ: The height of the antenna (m) above the node's Z coordinate
    .
    .
    .
  ns3::FriisPropagationLossModel
    Frequency: The carrier frequency (in Hz) at which propagation occurs (default is 5.15 GHz).
    SystemLoss: The system loss
    MinDistance: The distance under which the propagation model refuses to give results (m)
  */

  YansWifiPhyHelper wifiPhy = YansWifiPhyHelper::Default ();
  YansWifiChannelHelper wifiChannel = YansWifiChannelHelper();
  wifiChannel.SetPropagationDelay ("ns3::ConstantSpeedPropagationDelayModel");
  wifiChannel.AddPropagationLoss ("ns3::TwoRayGroundPropagationLossModel", "HeightAboveZ",
                                  DoubleValue (1.5), "SystemLoss", DoubleValue (1), "MinDistance",
                                  DoubleValue (m_MinDistance));
  // wifiChannel.AddPropagationLoss ("ns3::ItuR1411NlosOverRooftopPropagationLossModel", "Frequency",DoubleValue (5885e6),"Environment",EnumValue(ns3::UrbanEnvironment));
 
  wifiPhy.SetPcapDataLinkType (WifiPhyHelper::DLT_IEEE802_11);

  wifiPhy.Set ("TxPowerStart",
               DoubleValue (m_txPower_dBm)); //Minimum available transmission level (dbm)
  wifiPhy.Set ("TxPowerEnd",
               DoubleValue (m_txPower_dBm)); //Maximum available transmission level (dbm)
  //Number of transmission power levels available between TxPowerStart and TxPowerEnd included (default 8)
  wifiPhy.Set ("TxPowerLevels", UintegerValue (1));

  wifiPhy.SetPreambleDetectionModel ("ns3::ThresholdPreambleDetectionModel",
                                     "MinimumRssi", DoubleValue (m_MinimumRssi),
                                     "Threshold", DoubleValue (m_snr));
  wifiPhy.Set ("EnergyDetectionThreshold", DoubleValue (m_MinimumRssi));
  wifiPhy.Set ("RxSensitivity", DoubleValue (m_MinimumRssi));

  //wifiPhy.Set ("RxGain", DoubleValue (1));
  //wifiPhy.Set ("ShortPlcpPreambleSupported", BooleanValue(true) );
  //wifiPhy.Set ("TxPowerEnd", DoubleValue (16) );
  //wifiPhy.Set ("TxPowerStart", DoubleValue(16) );
  //wifiPhy.Set ("TxPowerLevels", UintegerValue(1) );
  //wifiPhy.Set ("TxGain", DoubleValue(1));
  //wifiPhy.Set ("Frequency", UintegerValue(5880)); //CH176
  //wifiPhy.Set ("ChannelWidth", UintegerValue(20));
  //wifiPhy.Set ("RxNoiseFigure", DoubleValue(7));
  //wifiPhy.Set ("TxAntennas", UintegerValue(1));
  //wifiPhy.Set ("RxAntennas", UintegerValue(5));
  //wifiPhy.Set ("Antennas", UintegerValue(1));
  //wifiPhy.Set ("ShortGuardEnabled", BooleanValue(true));

  wifiPhy.SetChannel (wifiChannel.Create ());

  NqosWaveMacHelper wifi80211pMac = NqosWaveMacHelper::Default ();
  wifi80211pMac.SetType (
      "ns3::OcbWifiMac"); //  in IEEE80211p MAC does not require any association between devices (similar to an adhoc WiFi MAC)...

  Wifi80211pHelper wifi80211p = Wifi80211pHelper::Default ();
  wifi80211p.SetRemoteStationManager ("ns3::ConstantRateWifiManager", "DataMode",
                                      StringValue (phyMode), "ControlMode", StringValue (phyMode),
                                      "NonUnicastMode", StringValue (phyMode));
  NetDeviceContainer wifiNetDevices = wifi80211p.Install (wifiPhy, wifi80211pMac, nodes);

  if (enablePcap)
    wifiPhy.EnablePcap ("PCAP", wifiNetDevices);

  return wifiNetDevices;
}
/*
  * 21dBm ~ 75m (radio coverage)
  * 33.8dbm ~ 200m  (radio coverage)
  * 45.6dbm~ 500m  (radio coverage)
*/
void
WifiSetupHelper::SetTxPower (double power)
{
  m_txPower_dBm = power;
}
/*
  * 21dBm ~ 75m (radio coverage)
  * 33.8dbm ~ 200m  (radio coverage)
  * 45.6dbm~ 500m  (radio coverage)
*/
void
WifiSetupHelper::SetMinDistance (double distance)
{
  m_MinDistance = distance;
}

void
WifiSetupHelper::SetMiniRssi (double rssi)
{
  m_MinimumRssi = rssi;
}

void
WifiSetupHelper::SetSnr (double snr)
{
  m_snr = snr;
}
} // namespace ndn
} // namespace ns3
