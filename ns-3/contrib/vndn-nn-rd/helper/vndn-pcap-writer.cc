/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-pcap-writer.cc
 * \brief Implementation of the VNDN PCAP trace writer (see vndn-pcap-writer.h).
 */

#include "ns3/vndn-pcap-writer.h"

namespace ns3 {
namespace ndn {

VndnPcapWriter::VndnPcapWriter (const std::string &file)
{
  PcapHelper helper;
  m_pcap = helper.CreateFile (file, std::ios::out, PcapHelper::DLT_PPP);
}

void
VndnPcapWriter::TracePacket (Ptr<const Packet> packet)
{
  static PppHeader pppHeader;
  pppHeader.SetProtocol (0x0077);
  m_pcap->Write (Simulator::Now (), pppHeader, packet);
}

} // namespace ndn
} // namespace ns3
