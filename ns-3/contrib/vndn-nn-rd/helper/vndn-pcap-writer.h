/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-pcap-writer.h
 * \brief PCAP trace writer for VNDN (Vehicular NDN) simulation.
 *
 * This helper wraps ns-3 PcapHelper to capture NDN packets on point-to-point
 * links into a single .pcap file. It is designed to be connected to the
 * MacTx trace source of PointToPointNetDevice.
 *
 * Usage from a scratch / example file:
 * \code
 *   #include "ns3/vndn-pcap-writer.h"
 *   ...
 *   ns3::ndn::VndnPcapWriter trace(pcapWriterFile);
 *   ns3::Config::ConnectWithoutContext(
 *       "/NodeList/ /DeviceList/ /$ns3::PointToPointNetDevice/MacTx",
 *       ns3::MakeCallback(&ns3::ndn::VndnPcapWriter::TracePacket, &trace));
 * \endcode
 */

#ifndef VNDN_PCAP_WRITER_H
#define VNDN_PCAP_WRITER_H

#include "ns3/core-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"

#include <string>

namespace ns3 {
namespace ndn {

/**
 * \brief Writes NDN packets on point-to-point links into a PCAP file.
 *
 * The writer creates a PCAP file with DLT_PPP encapsulation and writes every
 * traced packet with a PPP header whose protocol field is set to 0x0077
 * (the NDN protocol number used by ndnSIM).
 */
class VndnPcapWriter
{
public:
  /**
   * \brief Constructor.
   * \param file path of the output .pcap file
   *
   * Creates the PCAP file immediately. If the file cannot be created the
   * underlying PcapHelper will abort.
   */
  explicit
  VndnPcapWriter (const std::string &file);

  /**
   * \brief Trace callback to be connected to a MacTx (or similar) trace source.
   * \param packet the packet being transmitted
   *
   * Writes the packet into the PCAP file with the current simulation time
   * and a PPP header (protocol 0x0077).
   */
  void
  TracePacket (Ptr<const Packet> packet);

private:
  Ptr<PcapFileWrapper> m_pcap; ///< underlying PCAP file wrapper
};

} // namespace ndn
} // namespace ns3

#endif // VNDN_PCAP_WRITER_H
