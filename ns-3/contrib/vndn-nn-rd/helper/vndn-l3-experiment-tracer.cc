/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
#include "vndn-l3-experiment-tracer.h"
#include "ns3/ndnSIM/model/ndn-l3-protocol.hpp"
#include "ns3/ndnSIM/model/ndn-net-device-transport.hpp"
#include "ns3/node-list.h"
#include "ns3/simulator.h"
#include "ns3/callback.h"
#include <fstream>
#include <stdexcept>
#include <vector>

namespace vanet {
namespace {
std::string
Classify (const ndn::Name &name)
{
  static const std::vector<std::pair<ndn::Name, std::string>> classes = {
    {ndn::Name ("/vndn/control/hello"), "hello"},
    {ndn::Name ("/vndn/control/p2p-handshake"), "p2p_handshake"},
    {ndn::Name ("/vndn/control/rsu-relay/find"), "search"},
    {ndn::Name ("/vndn/control/rsu-relay/found"), "find"},
    {ndn::Name ("/vndn/control/rsu-relay/forward"), "relay_data"},
    {ndn::Name ("/vndn/control/neural-route"), "neural_route"},
    {ndn::Name ("/vndn/control/neural-pit"), "neural_pit"},
    {ndn::Name ("/com/baidu"), "business"}
  };
  for (const auto &entry : classes)
    if (entry.first.isPrefixOf (name))
      return entry.second;
  return "unknown";
}

std::string
Csv (const std::string &value)
{
  std::string result = "\"";
  for (char c : value)
    {
      if (c == '"')
        result += '"';
      result += c;
    }
  return result + '"';
}
} // namespace

struct VndnL3ExperimentTracer::Impl
{
  struct Observer
  {
    Impl &owner;
    ns3::Ptr<ns3::ndn::L3Protocol> l3;
    uint32_t nodeId;
    Observer (Impl &state, ns3::Ptr<ns3::Node> node)
      : owner (state), l3 (node->GetObject<ns3::ndn::L3Protocol> ()),
        nodeId (node->GetId ())
    {
      l3->TraceConnectWithoutContext ("OutInterests", ns3::MakeCallback (&Observer::Interest, this));
      l3->TraceConnectWithoutContext ("OutData", ns3::MakeCallback (&Observer::Data, this));
      l3->TraceConnectWithoutContext ("OutNack", ns3::MakeCallback (&Observer::Nack, this));
      l3->TraceConnectWithoutContext ("InData", ns3::MakeCallback (&Observer::ReceivedData, this));
    }
    ~Observer ()
    {
      l3->TraceDisconnectWithoutContext ("OutInterests", ns3::MakeCallback (&Observer::Interest, this));
      l3->TraceDisconnectWithoutContext ("OutData", ns3::MakeCallback (&Observer::Data, this));
      l3->TraceDisconnectWithoutContext ("OutNack", ns3::MakeCallback (&Observer::Nack, this));
      l3->TraceDisconnectWithoutContext ("InData", ns3::MakeCallback (&Observer::ReceivedData, this));
    }
    bool InWindow (const nfd::Face &face) const
    {
      const auto now = ns3::Simulator::Now ().GetNanoSeconds ();
      return !owner.closed && owner.startNs <= now && now < owner.endNs &&
          dynamic_cast<const ns3::ndn::NetDeviceTransport *> (face.getTransport ()) != nullptr;
    }
    void Write (const nfd::Face &face, const char *type, const ndn::Name &name,
                const VndnL3Description &description)
    {
      owner.output << ns3::Simulator::Now ().GetNanoSeconds () << ',' << nodeId << ','
                   << face.getId () << ",OUT," << type << ',' << Csv (name.toUri ()) << ','
                   << description.semanticClass << ',' << description.wireBytes << ','
                   << description.innerDataBytes << '\n';
    }
    void Interest (const ndn::Interest &packet, const nfd::Face &face)
    {
      if (InWindow (face))
        Write (face, "INTEREST", packet.getName (), VndnL3ExperimentTracer::Describe (packet));
    }
    void Data (const ndn::Data &packet, const nfd::Face &face)
    {
      if (InWindow (face))
        Write (face, "DATA", packet.getName (), VndnL3ExperimentTracer::Describe (packet));
    }
    void Nack (const ndn::lp::Nack &packet, const nfd::Face &face)
    {
      if (InWindow (face))
        Write (face, "NACK", packet.getInterest ().getName (),
               VndnL3ExperimentTracer::Describe (packet));
    }
    void ReceivedData (const ndn::Data &packet, const nfd::Face &face)
    {
      if (InWindow (face) && ndn::Name ("/com/baidu").isPrefixOf (packet.getName ()))
        owner.received << ns3::Simulator::Now ().GetNanoSeconds () << ',' << nodeId << ','
                       << face.getId () << ',' << Csv (packet.getName ().toUri ()) << '\n';
    }
  };
  int64_t startNs;
  int64_t endNs;
  bool closed = false;
  std::ofstream output;
  std::ofstream received;
  std::vector<std::unique_ptr<Observer>> observers;

  Impl (const std::string &directory, int64_t start, int64_t end)
    : startNs (start), endNs (end)
  {
    if (start < 0 || end <= start)
      throw std::invalid_argument ("Invalid L3 observation window");
    const std::string path = directory + "/packet-l3.csv";
    if (std::ifstream (path).good () || std::ifstream (directory + "/data-rx.csv").good ())
      throw std::runtime_error ("Refusing to overwrite existing L3 observations");
    output.open (path);
    received.open (directory + "/data-rx.csv");
    if (!output || !received)
      throw std::runtime_error ("Cannot create L3 observation files in " + directory);
    output.exceptions (std::ios::badbit | std::ios::failbit);
    received.exceptions (std::ios::badbit | std::ios::failbit);
    output << "time_ns,node_id,face_id,direction,packet_type,name,semantic_class,wire_bytes,inner_data_bytes\n";
    received << "time_ns,node_id,face_id,name\n";
  }
};

VndnL3ExperimentTracer::VndnL3ExperimentTracer (std::unique_ptr<Impl> impl)
  : m_impl (std::move (impl)) {}
VndnL3ExperimentTracer::~VndnL3ExperimentTracer () = default;
std::unique_ptr<VndnL3ExperimentTracer>
VndnL3ExperimentTracer::InstallAll (const std::string &directory, int64_t start, int64_t end)
{
  auto impl = std::unique_ptr<Impl> (new Impl (directory, start, end));
  for (auto it = ns3::NodeList::Begin (); it != ns3::NodeList::End (); ++it)
    if ((*it)->GetObject<ns3::ndn::L3Protocol> () != nullptr)
      impl->observers.emplace_back (new Impl::Observer (*impl, *it));
  return std::unique_ptr<VndnL3ExperimentTracer> (
      new VndnL3ExperimentTracer (std::move (impl)));
}
void VndnL3ExperimentTracer::Flush ()
{
  if (!m_impl->closed)
    {
      m_impl->output.flush ();
      m_impl->received.flush ();
    }
}
void VndnL3ExperimentTracer::Close ()
{
  if (!m_impl->closed)
    {
      Flush ();
      m_impl->closed = true;
      m_impl->observers.clear ();
      m_impl->output.close ();
      m_impl->received.close ();
    }
}
VndnL3Description VndnL3ExperimentTracer::Describe (const ndn::Interest &interest)
{
  std::string type = Classify (interest.getName ());
  if (type == "relay_data")
    type = "unknown"; // The current protocol uses Data for the business envelope.
  return {type, interest.wireEncode ().size (), 0};
}
VndnL3Description VndnL3ExperimentTracer::Describe (const ndn::Data &data)
{
  VndnL3Description description {Classify (data.getName ()), data.wireEncode ().size (), 0};
  if (description.semanticClass == "relay_data")
    {
      try
        {
          const auto &content = data.getContent ();
          ndn::Block wire (content.value (), content.value_size ());
          ndn::Data inner (wire);
          if (wire.size () != content.value_size () ||
              !ndn::Name ("/com/baidu").isPrefixOf (inner.getName ()))
            throw std::runtime_error ("Relay must contain exactly one business Data");
          description.innerDataBytes = wire.size ();
        }
      catch (const std::exception &)
        {
          description.semanticClass = "unknown";
        }
    }
  return description;
}
VndnL3Description VndnL3ExperimentTracer::Describe (const ndn::lp::Nack &)
{
  // Nack headers belong to LP. Count events separately, not fake full wire bytes.
  return {"native_nack", 0, 0};
}
} // namespace vanet
