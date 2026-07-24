/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-utils-helper.cc
 * \brief Implementation of the shared VNDN utilities (see vndn-utils-helper.h).
 */

#include "ns3/vndn-utils-helper.h"

#include <array>
#include <cstdio>
#include <memory>
#include <stdexcept>

namespace ns3 {
namespace ndn {

// definition of the static data member declared in the header
std::map<uint32_t, ns3::Time> VndnUtilsHelper::nodesDisable2Move;
const std::string VndnUtilsHelper::ndn4ivc_traces_folder = "contrib/vndn-nn-rd/traces";
void
VndnUtilsHelper::checkDisableNodes ()
{
  for (auto it = nodesDisable2Move.begin (), it_next = it; it != nodesDisable2Move.end ();
       it = it_next)
    {
      ++it_next;
      Ptr<Node> exNode = ns3::NodeList::GetNode (it->first);
      // NOTE:we'll put the node in a new position, outside the simulation
      // communication range, but this is just for better visualization mode
      if ((ns3::Time) ns3::Simulator::Now ().GetSeconds () - it->second > 1)
        {
          Ptr<ConstantPositionMobilityModel> mob =
              exNode->GetObject<ConstantPositionMobilityModel> ();
          mob->SetPosition (Vector ((double) exNode->GetId (), -4000 - (rand () % 25), -5000.0));
          nodesDisable2Move.erase (it);
        }
    }
  Simulator::Schedule (Seconds (1), &VndnUtilsHelper::checkDisableNodes);
}

void
VndnUtilsHelper::ScheduleDisableNodesCheck ()
{
  Simulator::Schedule (Seconds (1), &VndnUtilsHelper::checkDisableNodes);
}

std::string
VndnUtilsHelper::exec (const std::string &cmd)
{
  std::array<char, 128> buffer;
  std::string result;
  std::unique_ptr<FILE, decltype (&pclose)> pipe (popen (cmd.c_str(), "r"), pclose);
  if (!pipe)
    throw std::runtime_error ("exec failed!");
  while (fgets (buffer.data (), buffer.size (), pipe.get ()) != nullptr)
    result += buffer.data ();
  return result;
}

uint32_t
VndnUtilsHelper::GetVehicleCount (const std::string &contribFolder, const std::string &scenarioName,
                                  const std::string &routeFileName)
{
  // Build a shell command that counts the "vehicle id" entries in the SUMO
  // route file: <contribFolder>/traces/<scenarioName>/<routeFileName>.rou.xml
  std::string cmd = "echo `cat " + contribFolder + "/" + scenarioName + "/" +
                    routeFileName + ".rou.xml | grep 'vehicle id' | wc -l`";
  std::string output = exec (cmd);
  // trim leading/trailing whitespace before parsing
  size_t start = output.find_first_not_of (" \t\r\n");
  if (start == std::string::npos)
    return 0;
  size_t end = output.find_last_not_of (" \t\r\n");
  std::string trimmed = output.substr (start, end - start + 1);
  return static_cast<uint32_t> (std::stoul (trimmed));
}

} // namespace ndn
} // namespace ns3
