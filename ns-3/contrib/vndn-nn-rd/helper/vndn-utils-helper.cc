/* -*- Mode:C++; c-file-style:"gnu"; indent-tabs-mode:nil; -*- */
/**
 * \file vndn-utils-helper.cc
 * \brief Implementation of the shared VNDN utilities (see vndn-utils-helper.h).
 */

#include "ns3/vndn-utils-helper.h"

#include <rapidxml.hpp>

#include <array>
#include <cstdio>
#include <fstream>
#include <iterator>
#include <memory>
#include <stdexcept>
#include <vector>

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
  // Build the path to the SUMO route file:
  // <contribFolder>/traces/<scenarioName>/<routeFileName>.rou.xml
  std::string filePath = contribFolder + "/./" + scenarioName + "/" +
                         routeFileName + ".rou.xml";

  // Read the whole XML file into a buffer (rapidxml requires a mutable,
  // null-terminated buffer).
  std::ifstream theFile (filePath);
  if (!theFile.is_open ())
    {
      std::cerr << "VndnUtilsHelper::GetVehicleCount: cannot open " << filePath << std::endl;
      return 0;
    }
  std::vector<char> buffer ((std::istreambuf_iterator<char> (theFile)),
                            std::istreambuf_iterator<char> ());
  buffer.push_back ('\0');

  // Parse the buffer and count the <vehicle> nodes.
  rapidxml::xml_document<> doc;
  doc.parse<0> (&buffer[0]);
  rapidxml::xml_node<> *root_node = doc.first_node ("routes");
  if (!root_node)
    return 0;

  uint32_t count = 0;
  for (rapidxml::xml_node<> *vehicle_node = root_node->first_node ("vehicle"); vehicle_node;
       vehicle_node = vehicle_node->next_sibling ("vehicle"))
    {
      count++;
    }
  return count;
}

bool
VndnUtilsHelper::SaveSimulationConfig (
    const std::string &outputDir,
    const std::vector<std::pair<std::string, std::string>> &parameters,
    const std::string &fileName)
{
  std::string filePath = outputDir;
  if (!filePath.empty () && filePath.back () != '/')
    filePath += '/';
  filePath += fileName;

  std::ofstream file (filePath, std::ios::out | std::ios::trunc);
  if (!file.is_open ())
    return false;

  for (const auto &parameter : parameters)
    file << parameter.first << '=' << parameter.second << '\n';
  return file.good ();
}

} // namespace ndn
} // namespace ns3
